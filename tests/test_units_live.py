"""Live Oracle checks for the execution filter.

The filter is the only thing standing between a hallucinated or malformed
statement and the training set, so these prove it actually rejects things —
a 100% pass rate on the real pool is only meaningful if failure is reachable.
"""

from __future__ import annotations

import pytest

from orashift.db import oracle
from orashift.seed import load as seed_load
from orashift.seed import verify as seed_verify
from orashift.units.execute import run_unit, split_ddl
from orashift.units.types import Category, Source, Unit, UnitType

pytestmark = pytest.mark.db


def _unit(sql: str, unit_type: UnitType = UnitType.QUERY, **metadata: str) -> Unit:
    return Unit(
        unit_key="test",
        schema_name="retail",
        unit_type=unit_type,
        category=Category.DUAL,
        sql_text=sql,
        source=Source.TEMPLATE,
        metadata=metadata,
    )


@pytest.fixture
def ora(live_settings):
    with oracle.connect(live_settings) as conn:
        conn.call_timeout = 15_000
        yield conn


def test_valid_statement_is_accepted(ora):
    result = run_unit(ora, _unit("SELECT 1 AS v FROM dual"))
    assert result.ok
    assert result.row_count == 1


@pytest.mark.parametrize(
    ("label", "sql"),
    [
        ("syntax error", "SELCT * FROM dual"),
        ("unknown table", "SELECT * FROM no_such_table_xyz"),
        ("unknown column", "SELECT nope FROM retail_orders"),
        ("postgres function", "SELECT nextval('retail_order_seq') FROM dual"),
        ("postgres LIMIT", "SELECT order_id FROM retail_orders LIMIT 5"),
    ],
)
def test_broken_statements_are_rejected(ora, label: str, sql: str):
    result = run_unit(ora, _unit(sql))
    assert not result.ok, label
    assert result.error


def test_an_oversized_result_is_rejected(ora):
    """A cross join is not a useful unit, however valid it is."""
    result = run_unit(
        ora,
        _unit(
            "SELECT a.order_id FROM retail_order_items a, retail_order_items b, "
            "retail_order_items c"
        ),
    )
    assert not result.ok
    assert "exceeds" in (result.error or "")


def test_ddl_is_accepted_and_leaves_nothing_behind(ora):
    name = "tmp_pytest_ddl_probe"
    result = run_unit(
        ora,
        _unit(
            f"CREATE TABLE {name} (id NUMBER(10), label VARCHAR2(20))", UnitType.DDL, object_0=name
        ),
    )
    assert result.ok
    with ora.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM user_tables WHERE table_name = UPPER(:1)", [name])
        assert cursor.fetchone()[0] == 0, "scratch table was not cleaned up"


def test_broken_ddl_is_rejected_and_still_cleans_up(ora):
    name = "tmp_pytest_ddl_bad"
    result = run_unit(
        ora, _unit(f"CREATE TABLE {name} (id NOT_A_TYPE)", UnitType.DDL, object_0=name)
    )
    assert not result.ok
    with ora.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM user_tables WHERE table_name = UPPER(:1)", [name])
        assert cursor.fetchone()[0] == 0


def test_split_ddl_handles_a_bundled_table_and_index():
    statements = split_ddl("CREATE TABLE t (a NUMBER); CREATE INDEX i ON t (a)")
    assert len(statements) == 2


def test_dml_runs_and_is_rolled_back(ora):
    """The statement really does change rows, and the change really is undone."""
    table = "retail_orders"
    with ora.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {table}")
        before = seed_verify.digest_rows([tuple(r) for r in cursor.fetchall()])

    result = run_unit(
        ora,
        _unit(
            f"UPDATE {table} SET order_date = order_date + 1",
            UnitType.DML,
            affects_0=table,
        ),
    )
    assert result.ok
    assert result.row_count == 150, "the update should have touched every row"

    with ora.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {table}")
        after = seed_verify.digest_rows([tuple(r) for r in cursor.fetchall()])
    assert before == after, "rollback did not restore the table"


def test_dml_violating_a_constraint_is_rejected(ora):
    result = run_unit(
        ora,
        _unit(
            "UPDATE retail_orders SET status = 'NOT_A_STATUS' WHERE ROWNUM <= 1",
            UnitType.DML,
            affects_0="retail_orders",
        ),
    )
    assert not result.ok
    assert "ORA-02290" in (result.error or "")


def test_seed_data_survives_the_whole_filter_run(live_settings):
    """Nothing above may have permanently changed either database."""
    from orashift import catalog

    for schema_name in catalog.SCHEMA_NAMES:
        comparisons = seed_verify.compare_schema(live_settings, catalog.get_schema(schema_name))
        assert all(c.ok for c in comparisons), schema_name


def test_no_scratch_objects_remain(live_settings):
    with seed_load._connect(live_settings, seed_load.ORACLE) as conn, conn.cursor() as cursor:
        for kind, sql in [
            ("tables", "SELECT COUNT(*) FROM user_tables WHERE table_name LIKE 'TMP%'"),
            ("views", "SELECT COUNT(*) FROM user_views WHERE view_name LIKE 'TMP%'"),
            ("sequences", "SELECT COUNT(*) FROM user_sequences WHERE sequence_name LIKE 'TMP%'"),
        ]:
            cursor.execute(sql)
            assert cursor.fetchone()[0] == 0, kind
