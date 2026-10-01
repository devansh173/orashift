"""Structural invariants of the schema catalogue."""

from __future__ import annotations

import pytest

from orashift import catalog


def test_four_schemas_in_different_domains():
    assert catalog.SCHEMA_NAMES == ("retail", "hr", "library", "logistics")


def test_every_schema_has_four_to_six_tables():
    for schema in catalog.SCHEMAS.values():
        assert 4 <= len(schema.tables) <= 6, schema.name


def test_table_names_are_globally_unique():
    names = [table.name for _schema, table in catalog.iter_tables()]
    assert len(names) == len(set(names))


def test_every_table_is_prefixed_with_its_schema():
    for schema, table in catalog.iter_tables():
        assert table.name.startswith(f"{schema.name}_"), table.name


def test_column_names_are_unique_within_a_table():
    for _schema, table in catalog.iter_tables():
        names = table.column_names
        assert len(names) == len(set(names)), table.name


def test_every_table_has_at_least_one_non_nullable_column():
    for _schema, table in catalog.iter_tables():
        assert any(not column.nullable for column in table.columns), table.name


def test_held_out_schema_exists_and_is_one_of_the_four():
    assert catalog.HELD_OUT_SCHEMA in catalog.SCHEMAS


def test_get_schema_rejects_a_typo_with_a_useful_message():
    with pytest.raises(KeyError, match="unknown schema"):
        catalog.get_schema("retial")


def test_find_table_round_trips():
    schema, table = catalog.find_table("hr_employees")
    assert schema.name == "hr"
    assert "manager_id" in table.column_names


def test_self_referencing_hierarchies_exist_for_connect_by():
    # CONNECT BY coverage in phase 2 needs a parent pointer in both a training
    # schema and the held-out schema.
    _s, categories = catalog.find_table("retail_categories")
    assert "parent_category_id" in categories.column_names
    _s, legs = catalog.find_table("logistics_shipment_legs")
    assert "parent_leg_id" in legs.column_names
