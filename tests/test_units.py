"""The unit pool: templates, normalisation, storage and the LLM prompt helpers."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from orashift.units import llm, store, templates
from orashift.units.anchors import ANCHORS
from orashift.units.dedupe import normalize, unit_key
from orashift.units.generate import build_units
from orashift.units.types import Category, Source, Status, Unit, UnitType

# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #


def test_every_category_has_at_least_one_template():
    """Coverage guarantee: no construct on the project's list is unrepresented."""
    covered = {t.category for t in templates.ALL_TEMPLATES}
    missing = set(Category) - covered
    assert not missing, f"categories with no template: {sorted(c.value for c in missing)}"


def test_template_ids_are_unique():
    ids = [t.id for t in templates.ALL_TEMPLATES]
    assert len(ids) == len(set(ids))


def test_rendering_leaves_no_unresolved_placeholders():
    for _template, _anchors, sql, _combo in templates.render_all():
        assert "{" not in sql and "}" not in sql, sql


def test_rendering_is_deterministic():
    first = [sql for _t, _a, sql, _c in templates.render_all()]
    second = [sql for _t, _a, sql, _c in templates.render_all()]
    assert first == second


def test_templates_are_skipped_when_a_schema_lacks_the_anchor():
    """library has no self-referencing table, so it gets no CONNECT BY units."""
    library = ANCHORS["library"]
    assert not library.has("hier")
    connect_by = [t for t in templates.ALL_TEMPLATES if t.category is Category.CONNECT_BY]
    for template in connect_by:
        assert templates.render(template, library) == []


def test_connect_by_is_still_covered_by_other_schemas():
    rendered = [
        a.schema for t, a, _sql, _c in templates.render_all() if t.category is Category.CONNECT_BY
    ]
    assert set(rendered) == {"retail", "hr", "logistics"}


def test_ddl_templates_use_unique_scratch_names_per_schema():
    names = [
        sql
        for t, _a, sql, _c in templates.render_all()
        if t.unit_type is UnitType.DDL and t.needs_object
    ]
    assert names, "expected DDL templates with scratch objects"
    # Scratch names are prefixed so cleanup can find them.
    assert all("tmp_" in sql for sql in names)


def test_scratch_names_fit_oracle_identifier_limits():
    for template in templates.ALL_TEMPLATES:
        for schema in ANCHORS:
            for index in range(template.needs_object):
                name = templates.scratch_name(template.id, schema, index)
                assert len(name) <= 30, name


def test_dml_templates_declare_what_they_touch():
    """Without this the rollback check has nothing to compare."""
    for template in templates.ALL_TEMPLATES:
        if template.unit_type is UnitType.DML:
            assert template.affects, template.id


def test_sequence_units_are_flagged_as_not_value_comparable():
    """Two engines' sequences advance independently, so values cannot match."""
    for template in templates.ALL_TEMPLATES:
        if template.category is Category.SEQUENCE:
            assert not template.value_comparable, template.id


def test_pool_covers_all_four_schemas():
    schemas = Counter(a.schema for _t, a, _s, _c in templates.render_all())
    assert set(schemas) == set(ANCHORS)
    assert all(count > 20 for count in schemas.values()), schemas


# --------------------------------------------------------------------------- #
# Normalisation and dedupe
# --------------------------------------------------------------------------- #


def test_cosmetic_differences_collapse_to_one_key():
    a = "SELECT  order_id   FROM retail_orders WHERE ROWNUM <= 10"
    b = "select order_id from retail_orders where rownum <= 10"
    assert unit_key(a) == unit_key(b)


def test_semantic_differences_keep_separate_keys():
    a = "SELECT order_id FROM retail_orders WHERE ROWNUM <= 10"
    b = "SELECT order_id FROM retail_orders WHERE ROWNUM <= 11"
    assert unit_key(a) != unit_key(b)


def test_unparseable_sql_still_gets_a_key_and_is_marked_unparsed():
    canonical, parsed = normalize("this is not sql at all @@@")
    assert canonical
    assert parsed is False


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a FROM t START WITH p IS NULL CONNECT BY PRIOR a = p",
        "SELECT a FROM t, u WHERE t.a = u.b(+)",
        "SELECT * FROM t PIVOT (COUNT(x) FOR s IN (1 AS a))",
        "SELECT NVL(a, 0) FROM t",
        "SELECT a FROM t MINUS SELECT b FROM u",
    ],
)
def test_sqlglot_parses_the_oracle_isms_we_rely_on(sql: str):
    _canonical, parsed = normalize(sql)
    assert parsed


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #


def _unit(key: str, sql: str = "SELECT 1 FROM dual") -> Unit:
    return Unit(
        unit_key=key,
        schema_name="retail",
        unit_type=UnitType.QUERY,
        category=Category.DUAL,
        sql_text=sql,
        source=Source.TEMPLATE,
        normalized_sql=sql.lower(),
    )


def test_store_inserts_and_counts(tmp_path: Path):
    db = tmp_path / "u.sqlite"
    with store.connect(db) as conn:
        assert store.upsert_units(conn, [_unit("a"), _unit("b")]) == 2
        assert len(store.all_units(conn)) == 2


def test_store_ignores_a_duplicate_key(tmp_path: Path):
    db = tmp_path / "u.sqlite"
    with store.connect(db) as conn:
        store.upsert_units(conn, [_unit("a")])
        assert store.upsert_units(conn, [_unit("a")]) == 0


def test_a_verified_unit_is_not_reset_by_regeneration(tmp_path: Path):
    """This is what makes generation resumable."""
    db = tmp_path / "u.sqlite"
    with store.connect(db) as conn:
        store.upsert_units(conn, [_unit("a")])
        store.record_result(conn, "a", status=Status.VERIFIED, duration_ms=1.0, row_count=1)
    with store.connect(db) as conn:
        store.upsert_units(conn, [_unit("a")])
        assert store.all_units(conn)[0].status is Status.VERIFIED
        assert store.pending_units(conn) == []


def test_pending_and_verified_are_disjoint(tmp_path: Path):
    db = tmp_path / "u.sqlite"
    with store.connect(db) as conn:
        store.upsert_units(conn, [_unit("a"), _unit("b", "SELECT 2 FROM dual")])
        store.record_result(conn, "a", status=Status.VERIFIED)
        assert [u.unit_key for u in store.verified_units(conn)] == ["a"]
        assert [u.unit_key for u in store.pending_units(conn)] == ["b"]


def test_yield_report_groups_by_category(tmp_path: Path):
    db = tmp_path / "u.sqlite"
    with store.connect(db) as conn:
        store.upsert_units(conn, [_unit("a"), _unit("b", "SELECT 2 FROM dual")])
        store.record_result(conn, "a", status=Status.VERIFIED)
        store.record_result(conn, "b", status=Status.FAILED, error="boom")
        report = store.yield_report(conn)
    assert len(report) == 1
    assert report[0]["total"] == 2
    assert report[0]["verified"] == 1
    assert report[0]["failed"] == 1


def test_metadata_round_trips(tmp_path: Path):
    db = tmp_path / "u.sqlite"
    unit = Unit(
        unit_key="m",
        schema_name="retail",
        unit_type=UnitType.DDL,
        category=Category.DDL_TABLE,
        sql_text="CREATE TABLE x (a NUMBER)",
        source=Source.TEMPLATE,
        metadata={"object_0": "tmp_x", "value_comparable": "true"},
    )
    with store.connect(db) as conn:
        store.upsert_units(conn, [unit])
        assert store.all_units(conn)[0].metadata["object_0"] == "tmp_x"


# --------------------------------------------------------------------------- #
# build_units wiring
# --------------------------------------------------------------------------- #


def test_build_units_attaches_scratch_objects_to_ddl():
    ddl = [u for u in build_units() if u.unit_type is UnitType.DDL]
    assert ddl
    with_objects = [u for u in ddl if any(k.startswith("object_") for k in u.metadata)]
    assert with_objects


def test_build_units_resolves_affected_tables_for_dml():
    dml = [u for u in build_units() if u.unit_type is UnitType.DML]
    assert dml
    for unit in dml:
        affected = [v for k, v in unit.metadata.items() if k.startswith("affects_")]
        assert affected, unit.template_id
        # Resolved to a real table name, not left as the anchor name.
        assert all(name.startswith(unit.schema_name) for name in affected), affected


def test_build_units_keys_are_stable_across_calls():
    assert [u.unit_key for u in build_units()] == [u.unit_key for u in build_units()]


# --------------------------------------------------------------------------- #
# LLM helpers (the network call itself is not exercised)
# --------------------------------------------------------------------------- #


def test_llm_is_disabled_by_default(isolated_settings):
    settings = isolated_settings()
    assert settings.unit_llm_enabled is False
    assert llm.generate_units(settings, [Category.NVL]) == []


def test_llm_prompt_includes_the_schema_ddl_and_the_construct():
    messages = llm.build_messages("retail", Category.CONNECT_BY, 3)
    user = messages[1]["content"]
    assert "retail_categories" in user
    assert "connect_by" in user
    assert "3 different" in user


def test_llm_prompt_forbids_dml_and_markdown():
    system = llm.build_messages("hr", Category.NVL, 2)[0]["content"]
    assert "No DDL, no DML" in system
    assert "no markdown" in system


def test_llm_parser_strips_fences_numbering_and_semicolons():
    content = (
        "```sql\n"
        "1. SELECT order_id FROM retail_orders WHERE ROWNUM <= 5;\n"
        "2. SELECT customer_id FROM retail_customers ORDER BY customer_id\n"
        "```"
    )
    assert llm.parse_statements(content) == [
        "SELECT order_id FROM retail_orders WHERE ROWNUM <= 5",
        "SELECT customer_id FROM retail_customers ORDER BY customer_id",
    ]


def test_llm_parser_drops_non_select_statements():
    content = "DROP TABLE retail_orders\nSELECT 1 FROM dual\n-- a comment"
    assert llm.parse_statements(content) == ["SELECT 1 FROM dual"]


def test_llm_parser_keeps_cte_statements():
    assert llm.parse_statements("WITH a AS (SELECT 1 x FROM dual) SELECT x FROM a") == [
        "WITH a AS (SELECT 1 x FROM dual) SELECT x FROM a"
    ]


def test_llm_parser_on_empty_or_junk_input():
    assert llm.parse_statements("") == []
    assert llm.parse_statements("I cannot help with that.") == []
