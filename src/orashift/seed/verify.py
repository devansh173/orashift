"""Prove the two engines really do hold identical seed data.

Row counts alone are too weak: they would miss a mis-bound NULL, a truncated
string or a numeric that lost its scale. So every table is read back from both
engines, normalised into a canonical text form, and digested. Identical digests
mean identical values.

Normalisation exists because the same stored value can arrive as a different
Python object from each driver: Oracle returns ``NUMBER(12,2)`` holding 500.00
as ``Decimal('500')`` while PostgreSQL returns ``Decimal('500.00')``. Those are
numerically equal, so the canonical form strips insignificant trailing zeros
rather than comparing reprs.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from orashift.catalog import Schema, Table
from orashift.config import Settings
from orashift.seed.load import ORACLE, POSTGRES, Dialect, _connect

NULL_MARKER = "\x00NULL"
FIELD_SEPARATOR = "\x1f"
ROW_SEPARATOR = "\x1e"


def canonical(value: Any) -> str:
    """One stored value as engine-independent text."""
    if value is None:
        return NULL_MARKER
    if isinstance(value, Decimal):
        # normalize() drops insignificant trailing zeros; 'f' avoids 5E+2.
        return format(value.normalize(), "f")
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, dt.date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, bytes | bytearray):
        return bytes(value).hex()
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return format(Decimal(repr(value)).normalize(), "f")
    return str(value)


def digest_rows(rows: list[tuple[Any, ...]]) -> str:
    """A multiset digest: row order does not affect the result."""
    canonical_rows = sorted(FIELD_SEPARATOR.join(canonical(value) for value in row) for row in rows)
    hasher = hashlib.sha256()
    for row in canonical_rows:
        hasher.update(row.encode("utf-8"))
        hasher.update(ROW_SEPARATOR.encode("utf-8"))
    return hasher.hexdigest()


def read_table(cursor: Any, table: Table) -> list[tuple[Any, ...]]:
    columns = ", ".join(table.column_names)
    cursor.execute(f"SELECT {columns} FROM {table.name}")
    return [tuple(row) for row in cursor.fetchall()]


@dataclass(frozen=True, slots=True)
class TableComparison:
    table: str
    oracle_rows: int
    postgres_rows: int
    oracle_digest: str
    postgres_digest: str

    @property
    def counts_match(self) -> bool:
        return self.oracle_rows == self.postgres_rows

    @property
    def digests_match(self) -> bool:
        return self.oracle_digest == self.postgres_digest

    @property
    def ok(self) -> bool:
        return self.counts_match and self.digests_match


def _snapshot(settings: Settings, dialect: Dialect, schema: Schema) -> dict[str, tuple[int, str]]:
    result: dict[str, tuple[int, str]] = {}
    with _connect(settings, dialect) as conn, conn.cursor() as cursor:
        for table in schema.tables:
            rows = read_table(cursor, table)
            result[table.name] = (len(rows), digest_rows(rows))
    return result


def compare_schema(settings: Settings, schema: Schema) -> list[TableComparison]:
    """Read one schema back from both engines and compare it table by table."""
    oracle_side = _snapshot(settings, ORACLE, schema)
    postgres_side = _snapshot(settings, POSTGRES, schema)
    return [
        TableComparison(
            table=table.name,
            oracle_rows=oracle_side[table.name][0],
            postgres_rows=postgres_side[table.name][0],
            oracle_digest=oracle_side[table.name][1],
            postgres_digest=postgres_side[table.name][1],
        )
        for table in schema.tables
    ]
