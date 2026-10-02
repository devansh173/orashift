"""Verify a translation by running it on both engines and comparing.

One function per unit type, because "the same" means something different for
each:

* **query** — the result sets must match.
* **ddl** — the created object's catalogue metadata must satisfy the
  type-mapping policy. Running is necessary but not sufficient.
* **dml** — the affected tables must end up in the same state, measured inside
  a transaction that is then rolled back on both sides.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from orashift.seed.verify import digest_rows
from orashift.units.execute import MAX_ROWS, split_ddl
from orashift.verify import introspect
from orashift.verify.compare import (
    Comparison,
    ResultSet,
    compare_results,
    has_top_level_order_by,
)
from orashift.verify.introspect import SCRATCH_SCHEMA
from orashift.verify.typemap import check_columns


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    ok: bool
    reason: str | None = None
    detail: str | None = None
    duration_ms: float = 0.0
    oracle_rows: int | None = None
    postgres_rows: int | None = None
    ran_on_postgres: bool = False
    """True when the translation executed at all, even if the comparison failed.
    This is the 'runs without error' rate reported separately in phase 7."""


def _short(exc: Exception) -> str:
    return str(exc).strip().splitlines()[0][:400]


def _fetch(cursor: Any, sql: str) -> ResultSet:
    cursor.execute(sql)
    columns = tuple(d[0].lower() for d in cursor.description or ())
    rows = tuple(tuple(row) for row in cursor.fetchmany(MAX_ROWS + 1))
    return ResultSet(columns=columns, rows=rows)


def prepare_scratch_schema(pg_cursor: Any) -> None:
    """A dedicated schema for DDL units, so nothing can collide with seed tables."""
    pg_cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {SCRATCH_SCHEMA}")
    pg_cursor.execute(f"SET search_path TO {SCRATCH_SCHEMA}, public")


def drop_pg_objects(pg_cursor: Any, names: list[str]) -> None:
    for name in reversed(names):
        for statement in (
            f"DROP VIEW IF EXISTS {SCRATCH_SCHEMA}.{name} CASCADE",
            f"DROP TABLE IF EXISTS {SCRATCH_SCHEMA}.{name} CASCADE",
            f"DROP SEQUENCE IF EXISTS {SCRATCH_SCHEMA}.{name} CASCADE",
            f"DROP INDEX IF EXISTS {SCRATCH_SCHEMA}.{name} CASCADE",
        ):
            try:
                pg_cursor.execute(statement)
            except Exception:
                continue


def drop_oracle_objects(ora_cursor: Any, names: list[str]) -> None:
    for name in reversed(names):
        for statement in (
            f"DROP VIEW IF EXISTS {name}",
            f"DROP TABLE IF EXISTS {name} CASCADE CONSTRAINTS",
            f"DROP SEQUENCE IF EXISTS {name}",
            f"DROP INDEX IF EXISTS {name}",
        ):
            try:
                ora_cursor.execute(statement)
            except Exception:
                continue


def verify_query(
    ora_conn: Any,
    pg_conn: Any,
    oracle_sql: str,
    postgres_sql: str,
    *,
    compare_values: bool = True,
) -> VerificationOutcome:
    started = time.perf_counter()
    ordered = has_top_level_order_by(oracle_sql)

    with ora_conn.cursor() as ora_cursor:
        try:
            oracle_result = _fetch(ora_cursor, oracle_sql)
        except Exception as exc:
            return VerificationOutcome(
                False,
                "oracle side failed",
                _short(exc),
                (time.perf_counter() - started) * 1000,
            )

    with pg_conn.cursor() as pg_cursor:
        try:
            postgres_result = _fetch(pg_cursor, postgres_sql)
        except Exception as exc:
            pg_conn.rollback()
            return VerificationOutcome(
                False,
                "translation failed to run",
                _short(exc),
                (time.perf_counter() - started) * 1000,
                oracle_rows=len(oracle_result.rows),
            )

    comparison: Comparison = compare_results(
        oracle_result, postgres_result, ordered=ordered, compare_values=compare_values
    )
    return VerificationOutcome(
        ok=comparison.ok,
        reason=comparison.reason,
        detail=comparison.first_difference,
        duration_ms=(time.perf_counter() - started) * 1000,
        oracle_rows=len(oracle_result.rows),
        postgres_rows=len(postgres_result.rows),
        ran_on_postgres=True,
    )


def verify_ddl(
    ora_conn: Any,
    pg_conn: Any,
    oracle_sql: str,
    postgres_sql: str,
    objects: list[str],
) -> VerificationOutcome:
    """Create on both sides, compare catalogue metadata, then clean up.

    The PostgreSQL connection is switched to autocommit for the duration. In
    PostgreSQL any failed statement aborts the entire transaction, and catching
    the Python exception does not undo that: every later statement then fails
    with "current transaction is aborted". Since the speculative DROPs used for
    cleanup fail routinely and harmlessly, one of them would otherwise poison
    the connection for every unit that followed.
    """
    started = time.perf_counter()
    ran_on_postgres = False

    pg_conn.rollback()
    previous_autocommit = pg_conn.autocommit
    pg_conn.autocommit = True

    with ora_conn.cursor() as ora_cursor, pg_conn.cursor() as pg_cursor:
        try:
            prepare_scratch_schema(pg_cursor)
            drop_oracle_objects(ora_cursor, objects)
            drop_pg_objects(pg_cursor, objects)

            for statement in split_ddl(oracle_sql):
                ora_cursor.execute(statement)
            ora_conn.commit()

            try:
                for statement in split_ddl(postgres_sql):
                    pg_cursor.execute(statement)
                ran_on_postgres = True
            except Exception as exc:
                return VerificationOutcome(
                    False,
                    "translation failed to run",
                    _short(exc),
                    (time.perf_counter() - started) * 1000,
                )

            problems = _compare_ddl_metadata(ora_cursor, pg_cursor, objects)
            return VerificationOutcome(
                ok=not problems,
                reason="metadata does not match the type policy" if problems else None,
                detail="; ".join(problems[:4]) if problems else None,
                duration_ms=(time.perf_counter() - started) * 1000,
                ran_on_postgres=True,
            )
        except Exception as exc:
            return VerificationOutcome(
                False,
                "ddl verification error",
                _short(exc),
                (time.perf_counter() - started) * 1000,
                ran_on_postgres=ran_on_postgres,
            )
        finally:
            drop_oracle_objects(ora_cursor, objects)
            drop_pg_objects(pg_cursor, objects)
            ora_conn.commit()
            pg_conn.autocommit = previous_autocommit


def _compare_ddl_metadata(ora_cursor: Any, pg_cursor: Any, objects: list[str]) -> list[str]:
    """Check each created object. Tables and views by column, sequences and
    indexes by their own attributes."""
    problems: list[str] = []

    for name in objects:
        oracle_cols = introspect.oracle_columns(ora_cursor, name)
        if oracle_cols:
            pg_cols = introspect.pg_columns(pg_cursor, name)
            if not pg_cols:
                problems.append(f"{name}: not created in PostgreSQL")
                continue
            is_view = introspect.oracle_is_view(ora_cursor, name)
            problems.extend(
                f"{name}.{p}" for p in check_columns(oracle_cols, pg_cols, is_view=is_view)
            )
            continue

        oracle_seq = introspect.oracle_sequence(ora_cursor, name)
        if oracle_seq:
            pg_seq = introspect.pg_sequence(pg_cursor, name)
            if not pg_seq:
                problems.append(f"{name}: sequence not created in PostgreSQL")
            elif oracle_seq != pg_seq:
                # Only increment and cycle are compared: the two engines have
                # very different default bounds (Oracle's NUMBER maximum is far
                # beyond bigint), so comparing those would fail every time.
                problems.append(
                    f"{name}: sequence increment/cycle differ, "
                    f"oracle={oracle_seq} postgres={pg_seq}"
                )
            continue

        oracle_index = introspect.oracle_index_columns(ora_cursor, name)
        if oracle_index:
            pg_index = introspect.pg_index_columns(pg_cursor, name)
            if sorted(oracle_index) != sorted(pg_index):
                problems.append(
                    f"{name}: indexed columns differ, "
                    f"oracle={sorted(oracle_index)} postgres={sorted(pg_index)}"
                )
            continue

        problems.append(f"{name}: nothing found in the Oracle catalogue")

    return problems


def verify_dml(
    ora_conn: Any,
    pg_conn: Any,
    oracle_sql: str,
    postgres_sql: str,
    affected_tables: list[str],
    *,
    compare_values: bool = True,
) -> VerificationOutcome:
    """Apply on both sides inside a transaction, compare state, then roll back."""
    started = time.perf_counter()

    def snapshot(cursor: Any) -> dict[str, tuple[int, str]]:
        out: dict[str, tuple[int, str]] = {}
        for table in affected_tables:
            cursor.execute(f"SELECT * FROM {table}")
            rows = [tuple(row) for row in cursor.fetchall()]
            out[table] = (len(rows), digest_rows(rows))
        return out

    with ora_conn.cursor() as ora_cursor, pg_conn.cursor() as pg_cursor:
        try:
            ora_cursor.execute(oracle_sql)
            oracle_affected = ora_cursor.rowcount
            oracle_after = snapshot(ora_cursor)
        except Exception as exc:
            ora_conn.rollback()
            return VerificationOutcome(
                False,
                "oracle side failed",
                _short(exc),
                (time.perf_counter() - started) * 1000,
            )

        try:
            pg_cursor.execute(postgres_sql)
            postgres_affected = pg_cursor.rowcount
            postgres_after = snapshot(pg_cursor)
        except Exception as exc:
            ora_conn.rollback()
            pg_conn.rollback()
            return VerificationOutcome(
                False,
                "translation failed to run",
                _short(exc),
                (time.perf_counter() - started) * 1000,
            )

        ora_conn.rollback()
        pg_conn.rollback()

    elapsed = (time.perf_counter() - started) * 1000

    if oracle_affected != postgres_affected:
        return VerificationOutcome(
            False,
            "row count affected differs",
            f"oracle={oracle_affected} postgres={postgres_affected}",
            elapsed,
            ran_on_postgres=True,
        )

    if compare_values:
        differing = [t for t in affected_tables if oracle_after[t] != postgres_after[t]]
        if differing:
            return VerificationOutcome(
                False,
                "resulting table state differs",
                f"tables: {', '.join(differing)}",
                elapsed,
                ran_on_postgres=True,
            )

    return VerificationOutcome(
        True,
        duration_ms=elapsed,
        oracle_rows=oracle_affected,
        postgres_rows=postgres_affected,
        ran_on_postgres=True,
    )
