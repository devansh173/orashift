"""The seed generator: determinism, shape, and the no-empty-string rule."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest

from orashift import catalog
from orashift.seed import generate


def _digest_tree(root: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(root.rglob("*.csv")):
        hasher.update(path.relative_to(root).as_posix().encode())
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def test_generation_is_deterministic(tmp_path: Path):
    first, second = tmp_path / "a", tmp_path / "b"
    generate.generate_all(first)
    generate.generate_all(second)
    assert _digest_tree(first) == _digest_tree(second)


def test_committed_csvs_match_a_fresh_generation(tmp_path: Path):
    """Guards against a committed CSV being edited by hand."""
    generate.generate_all(tmp_path)
    assert _digest_tree(tmp_path) == _digest_tree(Path("data/seed"))


def test_every_catalogue_table_has_a_csv():
    for schema, table in catalog.iter_tables():
        assert generate.csv_path(Path("data/seed"), schema.name, table.name).exists()


def test_csv_headers_match_the_catalogue():
    for schema, table in catalog.iter_tables():
        path = generate.csv_path(Path("data/seed"), schema.name, table.name)
        with path.open(newline="", encoding="utf-8") as handle:
            header = next(csv.reader(handle))
        assert tuple(header) == table.column_names, table.name


def test_no_empty_strings_anywhere():
    """Oracle stores '' as NULL, so an empty string could never match across engines."""
    for schema, table in catalog.iter_tables():
        path = generate.csv_path(Path("data/seed"), schema.name, table.name)
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            next(reader)
            for line_no, row in enumerate(reader, start=2):
                # csv gives '' for both an empty field and a quoted "". The
                # generator writes NULL as an unquoted empty field, and the raw
                # text check below rules out the quoted form.
                assert len(row) == len(table.columns), f"{table.name}:{line_no}"
        assert ',""' not in path.read_text(encoding="utf-8"), table.name


def test_to_field_rejects_an_empty_text_value():
    with pytest.raises(ValueError, match="empty strings"):
        generate._to_field("", catalog.ValueKind.TEXT)


def test_null_renders_as_an_empty_field():
    assert generate._to_field(None, catalog.ValueKind.TEXT) == ""
    assert generate._to_field(None, catalog.ValueKind.TIMESTAMP) == ""


def test_generated_timestamps_carry_a_time():
    """An Oracle DATE holds a time; seed data must actually exercise that."""
    path = generate.csv_path(Path("data/seed"), "retail", "retail_customers")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        index = header.index("signup_date")
        times = {row[index].split(" ")[1] for row in reader}
    assert times != {"00:00:00"}
