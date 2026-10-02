"""The verifier: comparison rules, the type policy, and candidate rendering.

These are the rules that define "correct" for the whole project, so they are
tested directly rather than only through a live run.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from orashift.units import templates
from orashift.units.translations import TRANSLATIONS
from orashift.units.types import Category, Source, Unit, UnitType
from orashift.verify import ora2pg
from orashift.verify.candidates import CandidateSource, render_gold, render_sqlglot
from orashift.verify.compare import (
    ResultSet,
    canonical,
    compare_results,
    has_top_level_order_by,
)
from orashift.verify.typemap import OracleColumn, PgColumn, check_columns, expected_pg_type

# --------------------------------------------------------------------------- #
# Ordering detection
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("sql", "ordered"),
    [
        ("SELECT a FROM t ORDER BY a", True),
        ("SELECT a FROM t", False),
        ("SELECT * FROM (SELECT a FROM t ORDER BY a) q", False),
        ("SELECT a FROM t WHERE b IN (SELECT c FROM u ORDER BY c)", False),
        ("SELECT a FROM t CONNECT BY PRIOR a = b ORDER SIBLINGS BY a", True),
    ],
)
def test_only_a_top_level_order_by_counts(sql: str, ordered: bool):
    assert has_top_level_order_by(sql) is ordered


# --------------------------------------------------------------------------- #
# Value canonicalisation
# --------------------------------------------------------------------------- #


def test_the_precision_difference_that_motivated_this_compares_equal():
    """Oracle keeps 38 significant digits, PostgreSQL about 16."""
    assert canonical(Decimal("15.20833333333333333333333333333333333333")) == canonical(
        Decimal("15.2083333333333333")
    )


def test_trailing_zeros_do_not_matter():
    assert canonical(Decimal("500")) == canonical(Decimal("500.00"))


def test_genuinely_different_numbers_stay_different():
    assert canonical(Decimal("1.0")) != canonical(Decimal("1.1"))
    assert canonical(Decimal("0.0000001")) != canonical(Decimal("0.001"))


def test_canonical_number_never_uses_scientific_notation():
    assert "E" not in canonical(Decimal("1E+10"))


def test_null_is_distinct_from_strings_that_look_like_it():
    assert canonical(None) != canonical("NULL")
    assert canonical(None) != canonical("")


def test_integers_and_decimals_of_equal_value_agree():
    """Oracle returns Decimal where PostgreSQL may return int."""
    assert canonical(1) == canonical(Decimal("1"))


def test_timestamps_canonicalise_to_the_second():
    assert canonical(dt.datetime(2024, 3, 7, 14, 35, 59)) == "2024-03-07 14:35:59"


# --------------------------------------------------------------------------- #
# Result comparison
# --------------------------------------------------------------------------- #


def _rs(*rows: tuple) -> ResultSet:
    return ResultSet(columns=("a", "b"), rows=rows)


def test_row_order_is_ignored_without_an_order_by():
    assert compare_results(_rs((1, "x"), (2, "y")), _rs((2, "y"), (1, "x")), ordered=False).ok


def test_row_order_matters_with_an_order_by():
    assert not compare_results(_rs((1, "x"), (2, "y")), _rs((2, "y"), (1, "x")), ordered=True).ok


def test_duplicates_still_matter_in_a_multiset():
    assert not compare_results(_rs((1, "x")), _rs((1, "x"), (1, "x")), ordered=False).ok


def test_column_count_mismatch_is_reported_as_such():
    left = ResultSet(columns=("a",), rows=((1,),))
    right = ResultSet(columns=("a", "b"), rows=((1, 2),))
    result = compare_results(left, right, ordered=False)
    assert not result.ok
    assert "column count" in (result.reason or "")


def test_row_count_mismatch_is_reported_as_such():
    result = compare_results(_rs((1, "x")), _rs((1, "x"), (2, "y")), ordered=False)
    assert not result.ok
    assert "row count" in (result.reason or "")


def test_shape_only_comparison_ignores_values():
    """For an unordered ROWNUM each engine may legitimately pick different rows."""
    assert compare_results(_rs((1, "x")), _rs((9, "z")), ordered=False, compare_values=False).ok


def test_shape_only_comparison_still_catches_a_wrong_row_count():
    assert not compare_results(
        _rs((1, "x")), _rs((1, "x"), (2, "y")), ordered=False, compare_values=False
    ).ok


# --------------------------------------------------------------------------- #
# Type policy
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("oracle_type", "precision", "scale", "length", "expected"),
    [
        ("NUMBER", 4, 0, None, "smallint"),
        ("NUMBER", 9, 0, None, "integer"),
        ("NUMBER", 10, 0, None, "bigint"),
        ("NUMBER", 18, 0, None, "bigint"),
        ("NUMBER", 12, 2, None, "numeric(12,2)"),
        ("NUMBER", None, None, None, "numeric"),
        ("VARCHAR2", None, None, 60, "character varying(60)"),
        ("CHAR", None, None, 2, "character(2)"),
        ("CLOB", None, None, None, "text"),
        ("DATE", None, None, None, "timestamp without time zone(0)"),
        ("TIMESTAMP(6)", None, None, None, "timestamp without time zone(6)"),
        ("BLOB", None, None, None, "bytea"),
    ],
)
def test_policy_maps_each_oracle_type(oracle_type, precision, scale, length, expected):
    column = OracleColumn("c", oracle_type, precision, scale, length, True)
    assert expected_pg_type(column).describe() == expected


def test_money_never_maps_to_a_binary_float():
    """The most damaging possible mistake in this mapping."""
    mapped = expected_pg_type(OracleColumn("amount", "NUMBER", 12, 2, None, True))
    assert mapped.data_type == "numeric"
    assert "double" not in mapped.data_type


def test_identity_number_becomes_bigint_not_numeric():
    """PostgreSQL identity columns must be an integer type."""
    column = OracleColumn("id", "NUMBER", None, None, None, False, is_identity=True)
    assert expected_pg_type(column).describe() == "bigint"


def test_an_unknown_oracle_type_is_an_error_not_a_guess():
    with pytest.raises(KeyError):
        expected_pg_type(OracleColumn("c", "SDO_GEOMETRY", None, None, None, True))


def _pg(name: str, data_type: str, **kwargs) -> PgColumn:
    defaults = {
        "precision": None,
        "scale": None,
        "char_length": None,
        "datetime_precision": None,
        "nullable": True,
    }
    return PgColumn(name=name, data_type=data_type, **{**defaults, **kwargs})


def test_a_table_column_with_the_wrong_type_fails_the_policy():
    oracle = [OracleColumn("amount", "NUMBER", 12, 2, None, True)]
    actual = [_pg("amount", "double precision")]
    problems = check_columns(oracle, actual)
    assert problems and "policy requires" in problems[0]


def test_a_table_column_matching_the_policy_passes():
    oracle = [OracleColumn("amount", "NUMBER", 12, 2, None, True)]
    actual = [_pg("amount", "numeric", precision=12, scale=2)]
    assert check_columns(oracle, actual) == []


def test_nullability_difference_fails_for_a_table():
    oracle = [OracleColumn("id", "NUMBER", 10, 0, None, False)]
    actual = [_pg("id", "bigint", nullable=True)]
    assert check_columns(oracle, actual)


def test_views_are_checked_loosely_because_engines_infer_their_own_types():
    """COUNT(*) is NUMBER in Oracle and bigint in PostgreSQL; both are right."""
    oracle = [OracleColumn("n", "NUMBER", None, None, None, True)]
    actual = [_pg("n", "bigint")]
    assert check_columns(oracle, actual, is_view=True) == []
    # The same column in a table is held to the strict declared mapping.
    assert check_columns(oracle, actual, is_view=False) != []


def test_views_still_fail_on_a_different_type_family():
    oracle = [OracleColumn("n", "NUMBER", None, None, None, True)]
    actual = [_pg("n", "text")]
    assert check_columns(oracle, actual, is_view=True)


def test_column_order_difference_is_caught():
    oracle = [
        OracleColumn("a", "NUMBER", 10, 0, None, True),
        OracleColumn("b", "NUMBER", 10, 0, None, True),
    ]
    actual = [_pg("b", "bigint"), _pg("a", "bigint")]
    problems = check_columns(oracle, actual)
    assert problems and "order differ" in problems[0]


# --------------------------------------------------------------------------- #
# Candidates
# --------------------------------------------------------------------------- #


def test_every_template_has_a_translation():
    """Without this, a unit would have no gold target and silently drop out."""
    ids = {t.id for t in templates.ALL_TEMPLATES}
    assert ids == set(TRANSLATIONS), ids.symmetric_difference(TRANSLATIONS)


def test_no_translation_mentions_an_oracle_only_construct():
    """A cheap guard against pasting the Oracle side in by mistake."""
    banned = ("ROWNUM", "CONNECT BY", "NVL(", "DECODE(", " MINUS ", "SYSDATE", "FROM dual")
    for template_id, translation in TRANSLATIONS.items():
        upper = translation.sql.upper()
        for token in banned:
            assert token.upper() not in upper, f"{template_id} contains {token}"


def _unit(template_id: str, schema: str = "retail", **metadata: str) -> Unit:
    return Unit(
        unit_key="k",
        schema_name=schema,
        unit_type=UnitType.QUERY,
        category=Category.NVL,
        sql_text="SELECT 1 FROM dual",
        source=Source.TEMPLATE,
        template_id=template_id,
        metadata=metadata,
    )


def test_gold_renders_with_a_translated_parameter():
    """Oracle TRUNC(d,'MM') must become DATE_TRUNC('month', d)."""
    rendered = render_gold(_unit("trunc_date_unit", param_unit="MM"))
    assert rendered is not None
    assert "DATE_TRUNC('month'" in rendered


def test_gold_returns_none_for_an_unknown_template():
    assert render_gold(_unit("not_a_template")) is None


def test_sqlglot_leaves_connect_by_untranslated():
    """Recorded as a real baseline result, not an error."""
    unit = Unit(
        unit_key="k",
        schema_name="retail",
        unit_type=UnitType.QUERY,
        category=Category.CONNECT_BY,
        sql_text=(
            "SELECT category_id FROM retail_categories START WITH parent_category_id IS NULL "
            "CONNECT BY PRIOR category_id = parent_category_id"
        ),
        source=Source.TEMPLATE,
    )
    out = render_sqlglot(unit)
    assert out is not None
    assert "CONNECT BY" in out.upper()


def test_candidate_sources_are_named_as_the_store_expects():
    assert str(CandidateSource.GOLD) == "gold"
    assert str(CandidateSource.SQLGLOT) == "sqlglot"
    assert str(CandidateSource.ORA2PG) == "ora2pg"


# --------------------------------------------------------------------------- #
# Holdout design
# --------------------------------------------------------------------------- #


def test_held_out_template_ids_all_exist():
    ids = {t.id for t in templates.ALL_TEMPLATES}
    assert ids >= templates.HELD_OUT_TEMPLATES


def test_holdout_is_a_sensible_fraction():
    fraction = len(templates.HELD_OUT_TEMPLATES) / len(templates.ALL_TEMPLATES)
    assert 0.1 <= fraction <= 0.3


def test_every_category_survives_the_template_holdout():
    """Otherwise a whole construct would vanish from training."""
    training = {t.category for t in templates.training_templates()}
    everything = {t.category for t in templates.ALL_TEMPLATES}
    assert training == everything, everything - training


def test_training_and_held_out_templates_partition_the_set():
    train = {t.id for t in templates.training_templates()}
    held = {t.id for t in templates.held_out_templates()}
    assert not train & held
    assert {t.id for t in templates.ALL_TEMPLATES} == train | held


# --------------------------------------------------------------------------- #
# ora2pg output parsing
# --------------------------------------------------------------------------- #


def test_ora2pg_parser_drops_psql_meta_commands_without_losing_the_next_statement():
    """A backslash command has no semicolon, so a naive split swallows the DDL."""
    raw = (
        "SET client_encoding TO 'UTF8';\n"
        "\\set ON_ERROR_STOP ON\n"
        "CREATE TABLE tmp_a_0 (id bigint NOT NULL);\n"
        "ALTER TABLE tmp_a_0 ADD PRIMARY KEY (id);\n"
    )
    statements = ora2pg.split_output(raw)
    assert len(statements) == 2
    assert statements[0].startswith("CREATE TABLE tmp_a_0")


def test_ora2pg_statements_are_attributed_to_the_owning_object():
    statements = [
        "CREATE TABLE tmp_a_0 (id bigint)",
        "ALTER TABLE tmp_a_0 ADD PRIMARY KEY (id)",
        "CREATE TABLE tmp_b_0 (x integer)",
    ]
    owned = ora2pg.statements_for(statements, ["tmp_a_0"])
    assert len(owned) == 2
    assert all("tmp_a_0" in s for s in owned)


def test_ora2pg_attribution_does_not_leak_between_objects():
    statements = ["CREATE TABLE tmp_a_0 (id bigint)", "CREATE TABLE tmp_b_0 (x integer)"]
    assert ora2pg.statements_for(statements, ["tmp_b_0"]) == [statements[1]]
