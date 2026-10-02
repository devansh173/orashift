"""Run candidate units against Oracle and keep only the ones that work.

A template is just a guess. This module is what turns a guess into a fact: if a
statement does not execute on the pinned Oracle, it never enters the dataset.

Each unit type is run differently:

* **query** — executed and fetched, with a row cap and a call timeout.
* **ddl** — executed, then the objects it created are dropped again. Scratch
  objects are uniquely named per template and schema so two units can never
  collide.
* **dml** — executed inside a transaction. The affected tables are digested
  before and after, the statement's row count is recorded, and the transaction
  is then **rolled back**. A final digest confirms the rollback actually
  restored the table, so the seed data cannot be damaged by a verification run.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import oracledb

from orashift.seed.verify import digest_rows
from orashift.units.types import Unit, UnitType

MAX_ROWS = 10_000
"""Refuse a unit returning more than this. The seed data is small, so a result
this large means the statement is a cross join or similar, not a useful unit."""

DEFAULT_TIMEOUT_MS = 15_000


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    ok: bool
    duration_ms: float
    error: str | None = None
    row_count: int | None = None


def _short_error(exc: Exception) -> str:
    """First line of a driver error, which is the part that identifies it."""
    return str(exc).strip().splitlines()[0][:500]


def split_ddl(sql: str) -> list[str]:
    """DDL units may bundle two statements, e.g. a table and its index."""
    return [part.strip() for part in sql.split(";") if part.strip()]


def table_digest(cursor: oracledb.Cursor, table: str) -> tuple[int, str]:
    """Row count and value digest of a whole table, for before/after comparison."""
    cursor.execute(f"SELECT * FROM {table}")
    rows = [tuple(row) for row in cursor.fetchall()]
    return len(rows), digest_rows(rows)


def run_query(cursor: oracledb.Cursor, sql: str) -> ExecutionResult:
    started = time.perf_counter()
    try:
        cursor.execute(sql)
        rows = cursor.fetchmany(MAX_ROWS + 1)
    except Exception as exc:
        return ExecutionResult(False, (time.perf_counter() - started) * 1000, _short_error(exc))

    elapsed = (time.perf_counter() - started) * 1000
    if len(rows) > MAX_ROWS:
        return ExecutionResult(False, elapsed, f"result exceeds {MAX_ROWS} rows")
    return ExecutionResult(True, elapsed, row_count=len(rows))


def drop_scratch_objects(cursor: oracledb.Cursor, names: list[str]) -> None:
    """Best-effort cleanup. A unit that failed may have created nothing, or part."""
    for name in reversed(names):
        for statement in (
            f"DROP VIEW IF EXISTS {name}",
            f"DROP TABLE IF EXISTS {name} CASCADE CONSTRAINTS",
            f"DROP SEQUENCE IF EXISTS {name}",
            f"DROP INDEX IF EXISTS {name}",
        ):
            try:
                cursor.execute(statement)
            except Exception:
                # The object is of a different kind, or never existed. Both fine.
                continue


def run_ddl(
    conn: oracledb.Connection, cursor: oracledb.Cursor, sql: str, objects: list[str]
) -> ExecutionResult:
    started = time.perf_counter()
    try:
        for statement in split_ddl(sql):
            cursor.execute(statement)
        conn.commit()
        return ExecutionResult(True, (time.perf_counter() - started) * 1000)
    except Exception as exc:
        return ExecutionResult(False, (time.perf_counter() - started) * 1000, _short_error(exc))
    finally:
        # Always clean up, including after a partial success.
        drop_scratch_objects(cursor, objects)
        conn.commit()


def run_dml(
    conn: oracledb.Connection,
    cursor: oracledb.Cursor,
    sql: str,
    affected_tables: list[str],
) -> ExecutionResult:
    """Execute inside a transaction, then roll back and prove nothing changed."""
    started = time.perf_counter()
    try:
        before = {table: table_digest(cursor, table) for table in affected_tables}

        cursor.execute(sql)
        affected = cursor.rowcount
        elapsed = (time.perf_counter() - started) * 1000

        conn.rollback()

        after = {table: table_digest(cursor, table) for table in affected_tables}
        drifted = [table for table in affected_tables if before[table] != after[table]]
        if drifted:
            return ExecutionResult(
                False, elapsed, f"rollback did not restore: {', '.join(drifted)}"
            )
        return ExecutionResult(True, elapsed, row_count=affected)
    except Exception as exc:
        conn.rollback()
        return ExecutionResult(False, (time.perf_counter() - started) * 1000, _short_error(exc))


def run_unit(conn: oracledb.Connection, unit: Unit) -> ExecutionResult:
    """Dispatch a unit to the right runner for its type."""
    objects = [v for k, v in sorted(unit.metadata.items()) if k.startswith("object_")]
    affected = [v for k, v in sorted(unit.metadata.items()) if k.startswith("affects_")]

    with conn.cursor() as cursor:
        if unit.unit_type is UnitType.QUERY:
            return run_query(cursor, unit.sql_text)
        if unit.unit_type is UnitType.DDL:
            return run_ddl(conn, cursor, unit.sql_text, objects)
        return run_dml(conn, cursor, unit.sql_text, affected)
