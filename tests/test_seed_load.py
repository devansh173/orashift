"""Statement splitting, value coercion and placeholder generation."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from orashift import catalog
from orashift.catalog import ValueKind
from orashift.seed import load


def test_split_statements_drops_comment_lines_and_splits_on_semicolons():
    sql = """
    -- a leading comment
    CREATE TABLE a (x NUMBER);
    -- another comment
    CREATE INDEX i ON a (x);
    """
    statements = load.split_statements(sql)
    assert len(statements) == 2
    assert statements[0].startswith("CREATE TABLE a")
    assert statements[1].startswith("CREATE INDEX i")
    assert not any("comment" in s for s in statements)


def test_split_statements_ignores_a_trailing_semicolon():
    assert load.split_statements("SELECT 1;") == ["SELECT 1"]
    assert load.split_statements("SELECT 1;\n\n") == ["SELECT 1"]


def test_split_statements_on_empty_input():
    assert load.split_statements("") == []
    assert load.split_statements("-- only a comment\n") == []


@pytest.mark.parametrize(
    ("field", "kind", "expected"),
    [
        ("42", ValueKind.INT, 42),
        ("-7", ValueKind.INT, -7),
        ("1234.56", ValueKind.NUMERIC, Decimal("1234.56")),
        ("0.0001", ValueKind.NUMERIC, Decimal("0.0001")),
        ("hello", ValueKind.TEXT, "hello"),
        ("2024-03-07 14:35:59", ValueKind.TIMESTAMP, dt.datetime(2024, 3, 7, 14, 35, 59)),
    ],
)
def test_coerce_converts_each_kind(field, kind, expected):
    assert load.coerce(field, kind) == expected


@pytest.mark.parametrize("kind", list(ValueKind))
def test_an_empty_field_is_always_null(kind):
    assert load.coerce("", kind) is None


def test_numeric_coercion_keeps_exact_decimals():
    """A float would lose this; Decimal must not."""
    assert load.coerce("0.07", ValueKind.NUMERIC) == Decimal("0.07")
    assert load.coerce("0.07", ValueKind.NUMERIC) != float("0.07")


def test_oracle_uses_named_binds_and_postgres_positional():
    assert load.ORACLE.placeholders(3) == ":1, :2, :3"
    assert load.POSTGRES.placeholders(3) == "%s, %s, %s"


def test_ddl_exists_for_every_schema_and_dialect():
    for dialect in (load.ORACLE, load.POSTGRES):
        for name in catalog.SCHEMA_NAMES:
            assert dialect.ddl_path(name).exists(), f"{dialect.name}/{name}"


def test_read_rows_matches_the_catalogue_row_shape():
    schema, table = catalog.find_table("hr_pay_grades")
    rows = load.read_rows(table, Path("data/seed"), schema.name)
    assert len(rows) == 6
    assert all(len(row) == len(table.columns) for row in rows)


def test_read_rows_rejects_a_header_that_does_not_match(tmp_path: Path):
    schema, table = catalog.find_table("hr_pay_grades")
    path = tmp_path / schema.name / f"{table.name}.csv"
    path.parent.mkdir(parents=True)
    path.write_text("wrong,header\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match catalogue"):
        load.read_rows(table, tmp_path, schema.name)


def test_every_ddl_file_parses_into_statements():
    for dialect in (load.ORACLE, load.POSTGRES):
        for name in catalog.SCHEMA_NAMES:
            statements = load.split_statements(dialect.ddl_path(name).read_text(encoding="utf-8"))
            creates = [s for s in statements if s.upper().startswith("CREATE TABLE")]
            assert len(creates) == len(catalog.get_schema(name).tables)
