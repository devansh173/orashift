"""Assign each verified pair to a split.

Two generalisation axes are held out, giving four test sets rather than one:

    seen schema  x seen template    -> train, val, in-schema test
    seen schema  x unseen template  -> test_unseen_template
    unseen schema x seen template   -> test_unseen_schema
    unseen schema x unseen template -> test_unseen_both

Holding out a schema alone measures less than it appears to. If a template is
seen in training as `retail` and tested as `logistics`, the model has already
met that exact translation pattern and only the table names are new. Reporting
the two axes separately shows which kind of generalisation actually holds.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from enum import StrEnum
from typing import Any

from orashift.catalog import HELD_OUT_SCHEMA
from orashift.units.templates import HELD_OUT_TEMPLATES

VAL_EVERY = 10
"""Within the trainable bucket, every 10th example of each category becomes
validation and every 11th becomes in-schema test. Cycling through a sorted
order rather than sampling keeps the split deterministic and stratified."""

MIN_CATEGORY_FOR_SPLIT = 10
"""A category with fewer than this many trainable examples is kept entirely for
training. Splitting two DDL examples across three sets would leave a test set
whose score moves in 50-point steps."""


class Split(StrEnum):
    TRAIN = "train"
    VAL = "val"
    TEST_IN_SCHEMA = "test_in_schema"
    TEST_UNSEEN_SCHEMA = "test_unseen_schema"
    TEST_UNSEEN_TEMPLATE = "test_unseen_template"
    TEST_UNSEEN_BOTH = "test_unseen_both"


TEST_SPLITS = (
    Split.TEST_IN_SCHEMA,
    Split.TEST_UNSEEN_SCHEMA,
    Split.TEST_UNSEEN_TEMPLATE,
    Split.TEST_UNSEEN_BOTH,
)


def bucket_of(pair: dict[str, Any]) -> tuple[bool, bool]:
    """(schema is held out, template is held out)."""
    return (
        pair["schema_name"] == HELD_OUT_SCHEMA,
        pair["template_id"] in HELD_OUT_TEMPLATES,
    )


def assign_splits(pairs: Sequence[dict[str, Any]]) -> dict[str, Split]:
    """Map each unit key to its split. Deterministic given the same pairs."""
    assignment: dict[str, Split] = {}
    trainable: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for pair in pairs:
        unseen_schema, unseen_template = bucket_of(pair)
        if unseen_schema and unseen_template:
            assignment[pair["unit_key"]] = Split.TEST_UNSEEN_BOTH
        elif unseen_schema:
            assignment[pair["unit_key"]] = Split.TEST_UNSEEN_SCHEMA
        elif unseen_template:
            assignment[pair["unit_key"]] = Split.TEST_UNSEEN_TEMPLATE
        else:
            trainable[pair["category"]].append(pair)

    for category, members in trainable.items():
        ordered = sorted(members, key=lambda p: p["unit_key"])
        if len(ordered) < MIN_CATEGORY_FOR_SPLIT:
            for pair in ordered:
                assignment[pair["unit_key"]] = Split.TRAIN
            continue
        for index, pair in enumerate(ordered):
            position = index % VAL_EVERY
            if position == VAL_EVERY - 2:
                split = Split.VAL
            elif position == VAL_EVERY - 1:
                split = Split.TEST_IN_SCHEMA
            else:
                split = Split.TRAIN
            assignment[pair["unit_key"]] = split
        del category

    return assignment
