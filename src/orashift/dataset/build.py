"""Turn verified pairs into chat JSONL splits."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orashift.dataset.prompt import build_messages
from orashift.dataset.split import Split, assign_splits
from orashift.logging import get_logger
from orashift.units import store

log = get_logger(__name__)

DEFAULT_OUT_DIR = Path("data/dataset")
MAX_SEQ_LENGTH = 2048

CHARS_PER_TOKEN = 3.0
"""Conservative characters-per-token ratio used for the local estimate.

The real Qwen tokenizer cannot be run here: this machine's network blocks
huggingface.co, so the tokenizer cannot be downloaded. 3.0 deliberately
over-counts for SQL, which tokenises at roughly 3.5 to 4 characters per token,
so the estimate errs towards excluding an example rather than letting an
over-long one through. The training notebook re-measures with the real
tokenizer on Kaggle and reports the true exclusions.
"""


def estimate_tokens(text: str) -> int:
    """A deliberately pessimistic token estimate. Not a measurement."""
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def example_tokens(messages: list[dict[str, str]]) -> int:
    """Estimated length of the whole example, with a little chat-template overhead."""
    content = sum(estimate_tokens(m["content"]) for m in messages)
    return content + 8 * len(messages)


@dataclass(frozen=True, slots=True)
class BuildReport:
    counts: dict[str, int]
    excluded: int
    excluded_examples: list[tuple[str, int]]
    per_category: dict[str, dict[str, int]]
    thin_categories: list[tuple[str, int]]
    longest: int

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def build_example(pair: dict[str, Any], split: Split) -> dict[str, Any]:
    messages = build_messages(pair["oracle_sql"], pair["postgres_sql"], pair["schema_name"])
    return {
        "messages": messages,
        "meta": {
            "unit_key": pair["unit_key"],
            "schema": pair["schema_name"],
            "unit_type": pair["unit_type"],
            "category": pair["category"],
            "template_id": pair["template_id"],
            "split": str(split),
            "estimated_tokens": example_tokens(messages),
        },
    }


def build(
    out_dir: Path = DEFAULT_OUT_DIR,
    *,
    db_path: Path = store.DEFAULT_DB_PATH,
    max_tokens: int = MAX_SEQ_LENGTH,
) -> BuildReport:
    """Write one JSONL file per split and return what went where."""
    with store.connect(db_path) as conn:
        pairs = store.verified_pairs(conn, "gold")

    if not pairs:
        raise RuntimeError("no verified pairs found; run `orashift verify` first")

    splits = assign_splits(pairs)
    by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    per_category: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    excluded_examples: list[tuple[str, int]] = []
    longest = 0

    for pair in pairs:
        split = splits[pair["unit_key"]]
        example = build_example(pair, split)
        tokens = example["meta"]["estimated_tokens"]
        longest = max(longest, tokens)

        if tokens > max_tokens:
            excluded_examples.append((pair["unit_key"], tokens))
            continue

        by_split[str(split)].append(example)
        per_category[pair["category"]][str(split)] += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    for split in Split:
        path = out_dir / f"{split}.jsonl"
        examples = sorted(by_split.get(str(split), []), key=lambda e: e["meta"]["unit_key"])
        with path.open("w", encoding="utf-8") as handle:
            for example in examples:
                handle.write(json.dumps(example, ensure_ascii=False) + "\n")

    counts = {str(split): len(by_split.get(str(split), [])) for split in Split}

    train_counts = Counter(
        example["meta"]["category"] for example in by_split.get(str(Split.TRAIN), [])
    )
    thin = sorted(
        ((category, n) for category, n in train_counts.items() if n < 10),
        key=lambda item: item[1],
    )

    log.info("dataset_built", **counts, excluded=len(excluded_examples))
    return BuildReport(
        counts=counts,
        excluded=len(excluded_examples),
        excluded_examples=excluded_examples,
        per_category={k: dict(v) for k, v in per_category.items()},
        thin_categories=thin,
        longest=longest,
    )
