"""The type-mapping policy from docs/type-mapping.md, as executable rules.

DDL translations are not graded on whether they run. A `CREATE TABLE` that
executes but produces `double precision` where the policy requires
`numeric(12,2)` is wrong: it silently changes money arithmetic. So the
translated table is created, its catalogue metadata read back, and checked
against what the policy says the Oracle definition should have become.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TIMESTAMP = re.compile(r"^TIMESTAMP\((\d+)\)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class OracleColumn:
    name: str
    data_type: str
    precision: int | None
    scale: int | None
    char_length: int | None
    nullable: bool
    is_identity: bool = False


@dataclass(frozen=True, slots=True)
class PgColumn:
    name: str
    data_type: str
    """As information_schema.columns reports it, e.g. 'character varying'."""
    precision: int | None
    scale: int | None
    char_length: int | None
    datetime_precision: int | None
    nullable: bool
    is_identity: bool = False


@dataclass(frozen=True, slots=True)
class Expected:
    data_type: str
    precision: int | None = None
    scale: int | None = None
    char_length: int | None = None
    datetime_precision: int | None = None

    def describe(self) -> str:
        if self.char_length is not None:
            return f"{self.data_type}({self.char_length})"
        if self.precision is not None:
            return (
                f"{self.data_type}({self.precision},{self.scale})"
                if self.scale
                else f"{self.data_type}({self.precision})"
            )
        if self.datetime_precision is not None:
            return f"{self.data_type}({self.datetime_precision})"
        return self.data_type


def expected_pg_type(column: OracleColumn) -> Expected:
    """What the policy says this Oracle column must become in PostgreSQL."""
    oracle_type = column.data_type.upper()

    if oracle_type == "NUMBER":
        scale = column.scale or 0
        precision = column.precision

        if scale > 0:
            return Expected("numeric", precision=precision, scale=scale)

        if precision is None:
            # An unqualified NUMBER is exact-unbounded, so numeric. The one
            # exception is an identity column: PostgreSQL requires an integer
            # type there, so bigint is the mapping.
            return Expected("bigint") if column.is_identity else Expected("numeric")

        if precision <= 4:
            return Expected("smallint")
        if precision <= 9:
            return Expected("integer")
        if precision <= 18:
            return Expected("bigint")
        return Expected("numeric", precision=precision, scale=0)

    if oracle_type in {"VARCHAR2", "NVARCHAR2", "VARCHAR"}:
        return Expected("character varying", char_length=column.char_length)
    if oracle_type in {"CHAR", "NCHAR"}:
        return Expected("character", char_length=column.char_length)
    if oracle_type in {"CLOB", "NCLOB", "LONG"}:
        return Expected("text")
    if oracle_type == "DATE":
        return Expected("timestamp without time zone", datetime_precision=0)
    if match := _TIMESTAMP.match(oracle_type):
        return Expected("timestamp without time zone", datetime_precision=int(match.group(1)))
    if oracle_type == "TIMESTAMP":
        return Expected("timestamp without time zone", datetime_precision=6)
    if oracle_type in {"FLOAT", "BINARY_DOUBLE"}:
        return Expected("double precision")
    if oracle_type == "BINARY_FLOAT":
        return Expected("real")
    if oracle_type in {"RAW", "LONG RAW", "BLOB"}:
        return Expected("bytea")

    raise KeyError(f"no policy for Oracle type {column.data_type!r}")


def _matches(expected: Expected, actual: PgColumn) -> str | None:
    """None when the column satisfies the policy, otherwise why it does not."""
    if actual.data_type.lower() != expected.data_type:
        return f"type is {actual.data_type}, policy requires {expected.describe()}"
    if expected.char_length is not None and actual.char_length != expected.char_length:
        return f"length is {actual.char_length}, policy requires {expected.char_length}"
    if expected.precision is not None and actual.precision != expected.precision:
        return f"precision is {actual.precision}, policy requires {expected.precision}"
    if expected.scale is not None and (actual.scale or 0) != expected.scale:
        return f"scale is {actual.scale}, policy requires {expected.scale}"
    if (
        expected.datetime_precision is not None
        and actual.datetime_precision != expected.datetime_precision
    ):
        return (
            f"time precision is {actual.datetime_precision}, "
            f"policy requires {expected.datetime_precision}"
        )
    return None


NUMERIC_FAMILY = frozenset({"smallint", "integer", "bigint", "numeric", "real", "double precision"})
TEXT_FAMILY = frozenset({"character varying", "character", "text"})
TIME_FAMILY = frozenset({"timestamp without time zone", "timestamp with time zone", "date"})


def _same_family(expected: str, actual: str) -> bool:
    for family in (NUMERIC_FAMILY, TEXT_FAMILY, TIME_FAMILY):
        if expected in family and actual in family:
            return True
    return expected == actual


def check_columns(
    oracle_columns: list[OracleColumn],
    pg_columns: list[PgColumn],
    *,
    is_view: bool = False,
) -> list[str]:
    """Every way the PostgreSQL object fails to match the Oracle one. Empty is a pass.

    Views are checked more loosely than tables, for two reasons that are
    properties of the engines rather than of the translation:

    * A view column has no declared nullability. Oracle propagates the base
      column's NOT NULL into the view's catalogue entry; PostgreSQL reports
      every view column as nullable. Neither is wrong, and no translation can
      change it.
    * A view column's type is derived by each engine's own inference. COUNT(*)
      is NUMBER in Oracle and bigint in PostgreSQL, and bigint is the correct
      PostgreSQL type for a count. Demanding the declared-column mapping here
      would fail a correct translation.

    So for a view only the column names, their order, and the broad type family
    are enforced. Declared columns in tables are still checked exactly.
    """
    problems: list[str] = []

    oracle_names = [c.name.lower() for c in oracle_columns]
    pg_names = [c.name.lower() for c in pg_columns]
    if oracle_names != pg_names:
        return [f"column names or order differ: {oracle_names} vs {pg_names}"]

    for oracle_column, pg_column in zip(oracle_columns, pg_columns, strict=True):
        try:
            expected = expected_pg_type(oracle_column)
        except KeyError as exc:
            problems.append(f"{oracle_column.name}: {exc}")
            continue

        if is_view:
            if not _same_family(expected.data_type, pg_column.data_type.lower()):
                problems.append(
                    f"{oracle_column.name}: type family differs, oracle maps to "
                    f"{expected.data_type}, got {pg_column.data_type}"
                )
            continue

        if oracle_column.nullable != pg_column.nullable:
            problems.append(
                f"{oracle_column.name}: nullability differs "
                f"(oracle nullable={oracle_column.nullable})"
            )
        if problem := _matches(expected, pg_column):
            problems.append(f"{oracle_column.name}: {problem}")

    return problems
