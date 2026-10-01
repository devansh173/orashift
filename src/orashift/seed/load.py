"""Apply the schema DDL and load the seed CSVs into either engine.

The same CSV files feed both databases through parameterised inserts, so the
two sides cannot drift the way two hand-written sets of INSERT statements would.
"""

from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import oracledb

from orashift.catalog import Schema, Table, ValueKind
from orashift.config import Settings
from orashift.db import oracle, postgres
from orashift.logging import get_logger
from orashift.seed.generate import DEFAULT_OUT_DIR, TIMESTAMP_FORMAT, csv_path

log = get_logger(__name__)

DDL_ROOT = Path("sql/schemas")

_ORACLE_BIND_TYPES = {
    ValueKind.INT: oracledb.DB_TYPE_NUMBER,
    ValueKind.NUMERIC: oracledb.DB_TYPE_NUMBER,
    ValueKind.TIMESTAMP: oracledb.DB_TYPE_DATE,
    # 4000 is the maximum VARCHAR2 bind size. Oracle implicitly converts this
    # into the CLOB columns, and every generated value is far shorter.
    ValueKind.TEXT: 4000,
}


@dataclass(frozen=True, slots=True)
class Dialect:
    """The few places the two engines need different SQL."""

    name: str
    ddl_dirname: str
    drop_view: str
    drop_table: str
    drop_sequence: str
    named_binds: bool

    def placeholders(self, count: int) -> str:
        if self.named_binds:
            return ", ".join(f":{i}" for i in range(1, count + 1))
        return ", ".join(["%s"] * count)

    def ddl_path(self, schema_name: str) -> Path:
        return DDL_ROOT / self.ddl_dirname / f"{schema_name}.sql"


ORACLE = Dialect(
    name="oracle",
    ddl_dirname="oracle",
    # IF EXISTS on DROP arrived in Oracle 23c; this project pins 26ai.
    drop_view="DROP VIEW IF EXISTS {name}",
    drop_table="DROP TABLE IF EXISTS {name} CASCADE CONSTRAINTS",
    drop_sequence="DROP SEQUENCE IF EXISTS {name}",
    named_binds=True,
)

POSTGRES = Dialect(
    name="postgresql",
    ddl_dirname="postgres",
    drop_view="DROP VIEW IF EXISTS {name} CASCADE",
    drop_table="DROP TABLE IF EXISTS {name} CASCADE",
    drop_sequence="DROP SEQUENCE IF EXISTS {name} CASCADE",
    named_binds=False,
)

DIALECTS = {"oracle": ORACLE, "postgres": POSTGRES}


def split_statements(sql: str) -> list[str]:
    """Split a DDL script into statements.

    Deliberately simple: it drops whole-line ``--`` comments and splits on
    semicolons. That is sufficient for the schema files, which contain no
    PL/SQL blocks and no semicolons inside string literals. Anything richer
    would need a real parser.
    """
    body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    return [statement.strip() for statement in body.split(";") if statement.strip()]


def coerce(field: str, kind: ValueKind) -> Any:
    """Turn one CSV field into the Python value to bind. Empty field means NULL."""
    if field == "":
        return None
    if kind is ValueKind.INT:
        return int(field)
    if kind is ValueKind.NUMERIC:
        return Decimal(field)
    if kind is ValueKind.TIMESTAMP:
        return dt.datetime.strptime(field, TIMESTAMP_FORMAT)
    return field


def read_rows(table: Table, data_dir: Path, schema_name: str) -> list[tuple[Any, ...]]:
    """Read one table's CSV, checking the header matches the catalogue."""
    path = csv_path(data_dir, schema_name, table.name)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        if tuple(header) != table.column_names:
            raise ValueError(
                f"{path}: header {header} does not match catalogue {table.column_names}"
            )
        return [
            tuple(
                coerce(field, column.kind) for field, column in zip(row, table.columns, strict=True)
            )
            for row in reader
        ]


def drop_objects(cursor: Any, dialect: Dialect, schema: Schema) -> None:
    """Remove the schema's objects, newest dependency first. Safe if absent."""
    for view in schema.views:
        cursor.execute(dialect.drop_view.format(name=view))
    for table in reversed(schema.tables):
        cursor.execute(dialect.drop_table.format(name=table.name))
    for sequence in schema.sequences:
        cursor.execute(dialect.drop_sequence.format(name=sequence))


def apply_ddl(cursor: Any, dialect: Dialect, schema: Schema) -> int:
    """Run the hand-written CREATE statements for this schema and dialect."""
    sql = dialect.ddl_path(schema.name).read_text(encoding="utf-8")
    statements = split_statements(sql)
    for statement in statements:
        cursor.execute(statement)
    return len(statements)


def insert_rows(cursor: Any, dialect: Dialect, table: Table, rows: list[tuple[Any, ...]]) -> int:
    """Bulk insert one table's rows."""
    if not rows:
        return 0
    columns = ", ".join(table.column_names)
    sql = (
        f"INSERT INTO {table.name} ({columns}) VALUES ({dialect.placeholders(len(table.columns))})"
    )
    if dialect is ORACLE:
        # Bind types are declared rather than inferred from the first row: if
        # that row happened to hold NULL for a column, inference would guess
        # wrong for the whole batch.
        cursor.setinputsizes(*[_ORACLE_BIND_TYPES[c.kind] for c in table.columns])
    cursor.executemany(sql, rows)
    return len(rows)


def _connect(settings: Settings, dialect: Dialect) -> Any:
    if dialect is ORACLE:
        return oracle.connect(settings)
    return postgres.connect(settings, autocommit=False)


def seed_schema(
    settings: Settings,
    schema: Schema,
    dialect: Dialect,
    *,
    data_dir: Path = DEFAULT_OUT_DIR,
    drop: bool = True,
) -> dict[str, int]:
    """Create one schema and load its data into one engine. Idempotent when drop=True."""
    loaded: dict[str, int] = {}
    with _connect(settings, dialect) as conn, conn.cursor() as cursor:
        if drop:
            drop_objects(cursor, dialect, schema)
        statements = apply_ddl(cursor, dialect, schema)
        log.info("ddl_applied", engine=dialect.name, schema=schema.name, statements=statements)
        for table in schema.tables:
            rows = read_rows(table, data_dir, schema.name)
            loaded[table.name] = insert_rows(cursor, dialect, table, rows)
        conn.commit()
    log.info("schema_loaded", engine=dialect.name, schema=schema.name, rows=sum(loaded.values()))
    return loaded
