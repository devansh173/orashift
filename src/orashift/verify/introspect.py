"""Read object metadata back out of each engine's catalogue."""

from __future__ import annotations

from typing import Any

from orashift.verify.typemap import OracleColumn, PgColumn

SCRATCH_SCHEMA = "orashift_scratch"

_ORACLE_COLUMNS = """
SELECT column_name, data_type, data_precision, data_scale, char_length, nullable
FROM user_tab_columns
WHERE table_name = UPPER(:1)
ORDER BY column_id
"""

_ORACLE_IDENTITY = """
SELECT column_name FROM user_tab_identity_cols WHERE table_name = UPPER(:1)
"""

_PG_COLUMNS = """
SELECT column_name, data_type, numeric_precision, numeric_scale,
       character_maximum_length, datetime_precision, is_nullable, is_identity
FROM information_schema.columns
WHERE table_schema = %s AND table_name = %s
ORDER BY ordinal_position
"""

_ORACLE_SEQUENCE = """
SELECT increment_by, cycle_flag FROM user_sequences WHERE sequence_name = UPPER(:1)
"""

_PG_SEQUENCE = """
SELECT increment, cycle_option FROM information_schema.sequences
WHERE sequence_schema = %s AND sequence_name = %s
"""

_ORACLE_IS_VIEW = "SELECT COUNT(*) FROM user_views WHERE view_name = UPPER(:1)"

# A DESC key makes Oracle build a function-based index, so user_ind_columns
# reports a system-generated name like SYS_NC00004$ instead of the column. The
# real expression is in user_ind_expressions, so it is resolved from there.
_ORACLE_INDEX_COLUMNS = """
SELECT LOWER(ic.column_name), ie.column_expression
FROM user_ind_columns ic
     LEFT JOIN user_ind_expressions ie
            ON ie.index_name = ic.index_name
           AND ie.column_position = ic.column_position
WHERE ic.index_name = UPPER(:1)
ORDER BY ic.column_position
"""

_PG_INDEX_COLUMNS = """
SELECT a.attname
FROM pg_index i
JOIN pg_class c ON c.oid = i.indexrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
WHERE n.nspname = %s AND c.relname = %s
"""


def oracle_columns(cursor: Any, object_name: str) -> list[OracleColumn]:
    cursor.execute(_ORACLE_IDENTITY, [object_name])
    identity = {row[0].lower() for row in cursor.fetchall()}

    cursor.execute(_ORACLE_COLUMNS, [object_name])
    return [
        OracleColumn(
            name=name.lower(),
            data_type=data_type,
            precision=int(precision) if precision is not None else None,
            scale=int(scale) if scale is not None else None,
            char_length=int(char_length) if char_length else None,
            nullable=(nullable == "Y"),
            is_identity=name.lower() in identity,
        )
        for name, data_type, precision, scale, char_length, nullable in cursor.fetchall()
    ]


def pg_columns(cursor: Any, object_name: str, schema: str = SCRATCH_SCHEMA) -> list[PgColumn]:
    cursor.execute(_PG_COLUMNS, (schema, object_name.lower()))
    return [
        PgColumn(
            name=name.lower(),
            data_type=data_type,
            precision=precision,
            scale=scale,
            char_length=char_length,
            datetime_precision=datetime_precision,
            nullable=(is_nullable == "YES"),
            is_identity=(is_identity == "YES"),
        )
        for (
            name,
            data_type,
            precision,
            scale,
            char_length,
            datetime_precision,
            is_nullable,
            is_identity,
        ) in cursor.fetchall()
    ]


def oracle_sequence(cursor: Any, name: str) -> tuple[str, str] | None:
    cursor.execute(_ORACLE_SEQUENCE, [name])
    row = cursor.fetchone()
    return (str(row[0]), str(row[1]).strip().upper()[:1]) if row else None


def pg_sequence(cursor: Any, name: str, schema: str = SCRATCH_SCHEMA) -> tuple[str, str] | None:
    cursor.execute(_PG_SEQUENCE, (schema, name.lower()))
    row = cursor.fetchone()
    return (str(row[0]), str(row[1]).strip().upper()[:1]) if row else None


def oracle_is_view(cursor: Any, name: str) -> bool:
    cursor.execute(_ORACLE_IS_VIEW, [name])
    return bool(cursor.fetchone()[0])


def oracle_index_columns(cursor: Any, name: str) -> list[str]:
    cursor.execute(_ORACLE_INDEX_COLUMNS, [name])
    resolved: list[str] = []
    for column_name, expression in cursor.fetchall():
        if column_name.startswith("sys_nc") and expression:
            expression = str(expression)
            # e.g. '"B"' for a DESC key; strip the quoting back to the column.
            resolved.append(expression.strip().strip('"').lower())
        else:
            resolved.append(column_name)
    return resolved


def pg_index_columns(cursor: Any, name: str, schema: str = SCRATCH_SCHEMA) -> list[str]:
    cursor.execute(_PG_INDEX_COLUMNS, (schema, name.lower()))
    return [row[0] for row in cursor.fetchall()]
