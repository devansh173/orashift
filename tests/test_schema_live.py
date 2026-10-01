"""Live-database checks for the seeded schemas.

All `db` marked, so CI skips them. They are the real proof that the hand-written
PostgreSQL DDL is a faithful translation of the Oracle DDL, and they fail if the
Python catalogue ever drifts from what is actually in the databases.

These assume `orashift seed` has been run.
"""

from __future__ import annotations

import pytest

from orashift import catalog
from orashift.seed import load, verify

pytestmark = pytest.mark.db

ORACLE_COLUMNS_SQL = """
SELECT LOWER(column_name), nullable
FROM user_tab_columns
WHERE table_name = UPPER(:1)
ORDER BY column_id
"""

POSTGRES_COLUMNS_SQL = """
SELECT column_name, is_nullable
FROM information_schema.columns
WHERE table_schema = current_schema() AND table_name = %s
ORDER BY ordinal_position
"""


def _live_columns(settings, dialect: load.Dialect, table_name: str) -> list[tuple[str, bool]]:
    sql = ORACLE_COLUMNS_SQL if dialect is load.ORACLE else POSTGRES_COLUMNS_SQL
    truthy = "Y" if dialect is load.ORACLE else "YES"
    with load._connect(settings, dialect) as conn, conn.cursor() as cursor:
        cursor.execute(sql, [table_name])
        return [(name, flag == truthy) for name, flag in cursor.fetchall()]


@pytest.mark.parametrize("schema_name", catalog.SCHEMA_NAMES)
def test_oracle_matches_the_catalogue(live_settings, schema_name: str):
    for table in catalog.get_schema(schema_name).tables:
        live = _live_columns(live_settings, load.ORACLE, table.name)
        expected = [(c.name, c.nullable) for c in table.columns]
        assert live == expected, table.name


@pytest.mark.parametrize("schema_name", catalog.SCHEMA_NAMES)
def test_postgres_matches_the_catalogue(live_settings, schema_name: str):
    for table in catalog.get_schema(schema_name).tables:
        live = _live_columns(live_settings, load.POSTGRES, table.name)
        expected = [(c.name, c.nullable) for c in table.columns]
        assert live == expected, table.name


@pytest.mark.parametrize("schema_name", catalog.SCHEMA_NAMES)
def test_both_engines_agree_column_for_column(live_settings, schema_name: str):
    """Catches a column ordering or nullability difference between the dialects."""
    for table in catalog.get_schema(schema_name).tables:
        oracle_side = _live_columns(live_settings, load.ORACLE, table.name)
        postgres_side = _live_columns(live_settings, load.POSTGRES, table.name)
        assert oracle_side == postgres_side, table.name


@pytest.mark.parametrize("schema_name", catalog.SCHEMA_NAMES)
def test_seed_data_is_identical_across_engines(live_settings, schema_name: str):
    comparisons = verify.compare_schema(live_settings, catalog.get_schema(schema_name))
    assert comparisons, schema_name
    mismatched = [c.table for c in comparisons if not c.ok]
    assert not mismatched, f"differing tables: {mismatched}"


@pytest.mark.parametrize("schema_name", catalog.SCHEMA_NAMES)
def test_every_declared_view_is_queryable_on_both_engines(live_settings, schema_name: str):
    schema = catalog.get_schema(schema_name)
    for view in schema.views:
        for dialect in (load.ORACLE, load.POSTGRES):
            with load._connect(live_settings, dialect) as conn, conn.cursor() as cursor:
                cursor.execute(f"SELECT * FROM {view}")
                cursor.fetchall()


@pytest.mark.parametrize("schema_name", catalog.SCHEMA_NAMES)
def test_every_declared_sequence_exists_on_both_engines(live_settings, schema_name: str):
    schema = catalog.get_schema(schema_name)
    for sequence in schema.sequences:
        with load._connect(live_settings, load.ORACLE) as conn, conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM user_sequences WHERE sequence_name = UPPER(:1)",
                [sequence],
            )
            assert cursor.fetchone()[0] == 1, f"oracle: {sequence}"
        with load._connect(live_settings, load.POSTGRES) as conn, conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.sequences "
                "WHERE sequence_schema = current_schema() AND sequence_name = %s",
                [sequence],
            )
            assert cursor.fetchone()[0] == 1, f"postgres: {sequence}"
