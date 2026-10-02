"""The dataset build: splits, leakage, prompt shape and the card.

The leakage tests matter most. A single shared example between train and a test
split would inflate the headline accuracy and there would be no way to tell from
the numbers alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orashift.catalog import HELD_OUT_SCHEMA
from orashift.dataset import card
from orashift.dataset.build import (
    CHARS_PER_TOKEN,
    MAX_SEQ_LENGTH,
    build_example,
    estimate_tokens,
    example_tokens,
)
from orashift.dataset.prompt import build_messages, build_system_prompt, referenced_tables
from orashift.dataset.split import MIN_CATEGORY_FOR_SPLIT, Split, assign_splits, bucket_of
from orashift.units.templates import HELD_OUT_TEMPLATES

DATA_DIR = Path("data/dataset")


def _pair(key: str, schema: str, template: str, category: str = "rownum") -> dict:
    return {
        "unit_key": key,
        "schema_name": schema,
        "unit_type": "query",
        "category": category,
        "template_id": template,
        "oracle_sql": "SELECT order_id FROM retail_orders WHERE ROWNUM <= 5",
        "postgres_sql": "SELECT order_id FROM retail_orders LIMIT 5",
    }


# --------------------------------------------------------------------------- #
# Bucket logic
# --------------------------------------------------------------------------- #


def test_bucket_identifies_both_axes():
    held_template = next(iter(HELD_OUT_TEMPLATES))
    assert bucket_of(_pair("a", HELD_OUT_SCHEMA, held_template)) == (True, True)
    assert bucket_of(_pair("b", "retail", held_template)) == (False, True)
    assert bucket_of(_pair("c", HELD_OUT_SCHEMA, "rownum_inline")) == (True, False)
    assert bucket_of(_pair("d", "retail", "rownum_inline")) == (False, False)


def test_held_out_schema_never_reaches_training():
    pairs = [_pair(f"k{i}", HELD_OUT_SCHEMA, "rownum_inline") for i in range(30)]
    assigned = assign_splits(pairs)
    assert set(assigned.values()) == {Split.TEST_UNSEEN_SCHEMA}


def test_held_out_template_never_reaches_training():
    held = next(iter(HELD_OUT_TEMPLATES))
    pairs = [_pair(f"k{i}", "retail", held) for i in range(30)]
    assigned = assign_splits(pairs)
    assert set(assigned.values()) == {Split.TEST_UNSEEN_TEMPLATE}


def test_both_held_out_goes_to_the_hardest_bucket():
    held = next(iter(HELD_OUT_TEMPLATES))
    pairs = [_pair("k", HELD_OUT_SCHEMA, held)]
    assert assign_splits(pairs)["k"] is Split.TEST_UNSEEN_BOTH


def test_trainable_bucket_is_divided_into_three():
    pairs = [_pair(f"k{i:03d}", "retail", "rownum_inline") for i in range(40)]
    assigned = assign_splits(pairs)
    assert set(assigned.values()) == {Split.TRAIN, Split.VAL, Split.TEST_IN_SCHEMA}


def test_a_thin_category_is_kept_whole_for_training():
    """Splitting two examples across three sets gives a useless test set."""
    pairs = [
        _pair(f"k{i}", "retail", "rownum_inline", category="ddl_identity")
        for i in range(MIN_CATEGORY_FOR_SPLIT - 1)
    ]
    assigned = assign_splits(pairs)
    assert set(assigned.values()) == {Split.TRAIN}


def test_assignment_is_deterministic():
    pairs = [_pair(f"k{i:03d}", "retail", "rownum_inline") for i in range(40)]
    assert assign_splits(pairs) == assign_splits(list(reversed(pairs)))


def test_every_pair_gets_exactly_one_split():
    held = next(iter(HELD_OUT_TEMPLATES))
    pairs = (
        [_pair(f"a{i:03d}", "retail", "rownum_inline") for i in range(20)]
        + [_pair(f"b{i:03d}", HELD_OUT_SCHEMA, "rownum_inline") for i in range(5)]
        + [_pair(f"c{i:03d}", "retail", held) for i in range(5)]
    )
    assigned = assign_splits(pairs)
    assert len(assigned) == len(pairs)


# --------------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------------- #


def test_referenced_tables_finds_joined_tables():
    sql = (
        "SELECT o.order_id FROM retail_orders o "
        "JOIN retail_customers c ON c.customer_id = o.customer_id"
    )
    assert referenced_tables(sql, "retail") == ["retail_customers", "retail_orders"]


def test_referenced_tables_falls_back_when_sqlglot_cannot_parse():
    """CONNECT BY still has to produce the right context."""
    sql = (
        "SELECT category_id FROM retail_categories START WITH parent_category_id IS NULL "
        "CONNECT BY PRIOR category_id = parent_category_id"
    )
    assert referenced_tables(sql, "retail") == ["retail_categories"]


def test_system_prompt_includes_only_the_tables_used():
    prompt = build_system_prompt("SELECT order_id FROM retail_orders", "retail")
    assert "CREATE TABLE retail_orders" in prompt
    assert "CREATE TABLE library_books" not in prompt
    assert "CREATE TABLE retail_products" not in prompt


def test_system_prompt_survives_a_statement_with_no_known_tables():
    prompt = build_system_prompt("CREATE TABLE tmp_x (id NUMBER(10))", "retail")
    assert prompt
    assert "CREATE TABLE retail_orders" not in prompt


def test_system_prompt_states_the_semantic_traps():
    prompt = build_system_prompt("SELECT 1 FROM dual", "retail")
    for topic in ("DATE carries a time", "integer division", "NULL"):
        assert topic in prompt


def test_messages_are_system_user_assistant_in_order():
    messages = build_messages("SELECT 1 FROM dual", "SELECT 1", "retail")
    assert [m["role"] for m in messages] == ["system", "user", "assistant"]


def test_assistant_turn_is_the_translation_and_nothing_else():
    messages = build_messages("SELECT 1 FROM dual", "SELECT 1", "retail")
    assert messages[2]["content"] == "SELECT 1"
    assert "```" not in messages[2]["content"]


def test_the_answer_does_not_leak_into_the_prompt():
    """The model must not be able to read the target off the system or user turn."""
    oracle = "SELECT order_id FROM retail_orders WHERE ROWNUM <= 5"
    postgres = "SELECT order_id FROM retail_orders LIMIT 5"
    messages = build_messages(oracle, postgres, "retail")
    assert postgres not in messages[0]["content"]
    assert postgres not in messages[1]["content"]


# --------------------------------------------------------------------------- #
# Token estimation
# --------------------------------------------------------------------------- #


def test_token_estimate_over_counts_on_purpose():
    """Real SQL tokenises at roughly 3.5-4 chars per token; this assumes 3."""
    assert CHARS_PER_TOKEN <= 3.5
    text = "SELECT order_id FROM retail_orders WHERE ROWNUM <= 5"
    assert estimate_tokens(text) > len(text.split())


def test_example_tokens_counts_every_turn():
    messages = build_messages("SELECT 1 FROM dual", "SELECT 1", "retail")
    assert example_tokens(messages) > estimate_tokens(messages[0]["content"])


def test_build_example_records_its_own_length():
    example = build_example(_pair("k", "retail", "rownum_inline"), Split.TRAIN)
    assert example["meta"]["estimated_tokens"] == example_tokens(example["messages"])


# --------------------------------------------------------------------------- #
# The built files
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def built() -> dict[str, list[dict]]:
    if not (DATA_DIR / "train.jsonl").exists():
        pytest.skip("dataset not built; run `orashift build-dataset`")
    out = {}
    for split in Split:
        path = DATA_DIR / f"{split}.jsonl"
        with path.open(encoding="utf-8") as handle:
            out[str(split)] = [json.loads(line) for line in handle if line.strip()]
    return out


def test_every_split_file_is_valid_jsonl(built):
    assert built["train"], "training split is empty"
    for examples in built.values():
        for example in examples:
            assert set(example) == {"messages", "meta"}
            assert len(example["messages"]) == 3


def test_no_unit_appears_in_two_splits(built):
    seen: dict[str, str] = {}
    for split, examples in built.items():
        for example in examples:
            key = example["meta"]["unit_key"]
            assert key not in seen, f"{key} is in both {seen.get(key)} and {split}"
            seen[key] = split


def test_no_oracle_statement_is_shared_between_train_and_any_test(built):
    """Key-level separation is not enough: identical SQL under a different key
    would still be memorisation rather than generalisation."""
    train_sql = {e["messages"][1]["content"] for e in built["train"]}
    for split in (
        Split.TEST_IN_SCHEMA,
        Split.TEST_UNSEEN_SCHEMA,
        Split.TEST_UNSEEN_TEMPLATE,
        Split.TEST_UNSEEN_BOTH,
    ):
        overlap = train_sql & {e["messages"][1]["content"] for e in built[str(split)]}
        assert not overlap, f"{split} shares statements with train: {list(overlap)[:3]}"


def test_held_out_schema_appears_in_no_training_example(built):
    for example in built["train"] + built["val"]:
        assert example["meta"]["schema"] != HELD_OUT_SCHEMA


def test_held_out_templates_appear_in_no_training_example(built):
    for example in built["train"] + built["val"]:
        assert example["meta"]["template_id"] not in HELD_OUT_TEMPLATES


def test_unseen_schema_split_contains_only_the_held_out_schema(built):
    for example in built[str(Split.TEST_UNSEEN_SCHEMA)]:
        assert example["meta"]["schema"] == HELD_OUT_SCHEMA
        assert example["meta"]["template_id"] not in HELD_OUT_TEMPLATES


def test_unseen_both_split_is_held_out_on_both_axes(built):
    for example in built[str(Split.TEST_UNSEEN_BOTH)]:
        assert example["meta"]["schema"] == HELD_OUT_SCHEMA
        assert example["meta"]["template_id"] in HELD_OUT_TEMPLATES


def test_every_test_split_has_examples(built):
    for split in (
        Split.TEST_IN_SCHEMA,
        Split.TEST_UNSEEN_SCHEMA,
        Split.TEST_UNSEEN_TEMPLATE,
        Split.TEST_UNSEEN_BOTH,
    ):
        assert built[str(split)], f"{split} is empty, so it measures nothing"


def test_nothing_exceeds_the_token_budget(built):
    for examples in built.values():
        for example in examples:
            assert example["meta"]["estimated_tokens"] <= MAX_SEQ_LENGTH


def test_the_dataset_card_exists_and_is_not_a_stub():
    path = DATA_DIR / "README.md"
    if not path.exists():
        pytest.skip("dataset not built")
    text = path.read_text(encoding="utf-8")
    assert "Honest limitations" in text
    assert "estimates, not measurements" in text
    assert HELD_OUT_SCHEMA in text


def test_card_renders_from_a_report():
    from orashift.dataset.build import BuildReport

    report = BuildReport(
        counts={str(s): 1 for s in Split},
        excluded=0,
        excluded_examples=[],
        per_category={"rownum": {"train": 1}},
        thin_categories=[("pivot", 2)],
        longest=100,
    )
    text = card.render(report)
    assert "pivot" in text
    assert "## Splits" in text


# --------------------------------------------------------------------------- #
# Notebooks
#
# These run on Kaggle, not here, so they cannot be executed by the test suite.
# Static checking is what stops a typo from wasting a 40-minute GPU session.
# --------------------------------------------------------------------------- #


def test_every_notebook_cell_is_valid_python():
    import sys

    sys.path.insert(0, "scripts")
    from check_notebooks import check  # type: ignore[import-not-found]

    notebooks = sorted(Path("notebooks").glob("*.ipynb"))
    assert notebooks, "no notebooks found"
    for path in notebooks:
        assert check(path) == [], f"{path} failed static checks"


def test_the_training_notebook_says_it_is_unverified():
    """It ships unrun, and must not imply otherwise."""
    text = Path("notebooks/train_qlora.ipynb").read_text(encoding="utf-8")
    assert "has not been executed by its author" in text
