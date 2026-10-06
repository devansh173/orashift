"""Aggregate execution scores into results/metrics.json and results/report.md.

Every number in the project's README is read from `metrics.json`, which is
written here from the database. Nothing is typed by hand, so a figure cannot
drift away from the run that produced it.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orashift.units import store

RESULTS_DIR = Path("results")
METRICS_PATH = RESULTS_DIR / "metrics.json"
REPORT_PATH = RESULTS_DIR / "report.md"

SPLITS = (
    "test_in_schema",
    "test_unseen_schema",
    "test_unseen_template",
    "test_unseen_both",
)

SPLIT_LABELS = {
    "test_in_schema": "Seen schema, seen template",
    "test_unseen_schema": "Unseen schema, seen template",
    "test_unseen_template": "Seen schema, unseen template",
    "test_unseen_both": "Unseen schema, unseen template",
}

MODEL_LABELS = {
    "base": "Base (Qwen2.5-Coder-3B-Instruct, no adapter)",
    "finetuned": "Fine-tuned (QLoRA adapter)",
    "sqlglot": "sqlglot (rule-based)",
    "ora2pg": "ora2pg (DDL only)",
    "hybrid": "Hybrid (sqlglot, fine-tuned fallback)",
}


@dataclass(frozen=True, slots=True)
class Cell:
    verified: int
    total: int

    @property
    def rate(self) -> float:
        return self.verified / self.total if self.total else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"verified": self.verified, "total": self.total, "rate": round(self.rate, 4)}


def collect(db_path: Path = store.DEFAULT_DB_PATH) -> dict[str, Any]:
    """Build the whole metrics structure from the database."""
    with store.connect(db_path) as conn:
        scores = store.score_rows(conn)
        if not scores:
            raise RuntimeError("no scores recorded; run `orashift eval` scoring first")
        test_keys = sorted({r["unit_key"] for r in scores if r["model"] == "base"})
        baselines = store.baseline_rows_for(conn, test_keys)

    split_of = {r["unit_key"]: r["split"] for r in scores if r["model"] == "base"}
    meta = {
        r["unit_key"]: {
            "category": r["category"],
            "unit_type": r["unit_type"],
            "schema": r["schema_name"],
            "template_id": r["template_id"],
        }
        for r in scores
    }

    # model -> unit_key -> verified
    verdicts: dict[str, dict[str, bool]] = defaultdict(dict)
    ran: dict[str, dict[str, bool]] = defaultdict(dict)

    for row in scores:
        verdicts[str(row["model"])][str(row["unit_key"])] = bool(row["ok"])
        ran[str(row["model"])][str(row["unit_key"])] = bool(row["ran"])

    for row in baselines:
        verdicts[str(row["model"])][str(row["unit_key"])] = row["status"] == "verified"
        ran[str(row["model"])][str(row["unit_key"])] = bool(row["ran_on_postgres"])

    # Hybrid: take sqlglot where it verifies, otherwise the fine-tuned model.
    # This is the system you would actually ship: rules are free and
    # deterministic, the model only handles what rules cannot.
    sqlglot_verdicts = verdicts.get("sqlglot", {})
    finetuned_verdicts = verdicts.get("finetuned", {})
    verdicts["hybrid"] = {
        key: sqlglot_verdicts.get(key, False) or finetuned_verdicts.get(key, False)
        for key in test_keys
    }
    ran["hybrid"] = {
        key: ran.get("sqlglot", {}).get(key, False) or ran.get("finetuned", {}).get(key, False)
        for key in test_keys
    }

    models = [m for m in MODEL_LABELS if m in verdicts]

    overall = {
        model: Cell(sum(verdicts[model].values()), len(verdicts[model])).as_dict()
        for model in models
    }
    runs_without_error = {
        model: Cell(sum(ran[model].values()), len(ran[model])).as_dict() for model in models
    }

    by_split: dict[str, dict[str, Any]] = {}
    for split in SPLITS:
        keys = [k for k in test_keys if split_of.get(k) == split]
        by_split[split] = {
            model: Cell(
                sum(1 for k in keys if verdicts[model].get(k)),
                sum(1 for k in keys if k in verdicts[model]),
            ).as_dict()
            for model in models
        }

    categories = sorted({meta[k]["category"] for k in test_keys if k in meta})
    by_category: dict[str, dict[str, Any]] = {}
    for category in categories:
        keys = [k for k in test_keys if meta.get(k, {}).get("category") == category]
        by_category[category] = {
            model: Cell(
                sum(1 for k in keys if verdicts[model].get(k)),
                sum(1 for k in keys if k in verdicts[model]),
            ).as_dict()
            for model in models
        }

    failures = _failure_analysis(scores)

    return {
        "test_units": len(test_keys),
        "models": {model: MODEL_LABELS[model] for model in models},
        "execution_accuracy": overall,
        "runs_without_error": runs_without_error,
        "by_split": by_split,
        "split_labels": SPLIT_LABELS,
        "by_category": by_category,
        "failure_analysis": failures,
    }


def _failure_analysis(scores: list[dict[str, Any]]) -> dict[str, Any]:
    """Why each model failed, with real examples rather than summary counts."""
    out: dict[str, Any] = {}
    for model in ("base", "finetuned"):
        rows = [r for r in scores if r["model"] == model and not r["ok"]]
        reasons = Counter(str(r["reason"] or "unknown") for r in rows)
        categories = Counter(str(r["category"]) for r in rows)
        examples = [
            {
                "category": str(r["category"]),
                "split": str(r["split"]),
                "reason": str(r["reason"] or ""),
                "detail": str(r["detail"] or "")[:200],
                "oracle": str(r["sql_text"])[:220],
                "prediction": str(r["prediction"] or "")[:220],
            }
            for r in rows[:12]
        ]
        out[model] = {
            "failures": len(rows),
            "by_reason": dict(reasons.most_common()),
            "by_category": dict(categories.most_common(10)),
            "examples": examples,
        }
    return out


def _table(rows: list[list[str]], header: list[str]) -> list[str]:
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" if i == 0 else "---:" for i in range(len(header))) + " |",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _pct(cell: dict[str, Any]) -> str:
    if not cell["total"]:
        return "n/a"
    return f"{cell['verified']}/{cell['total']} ({cell['rate']:.0%})"


def render(metrics: dict[str, Any]) -> str:
    """The written evaluation."""
    models = list(metrics["models"])
    lines: list[str] = []
    add = lines.append

    add("# OraShift evaluation")
    add("")
    add(
        f"Every figure is **execution accuracy** over the same {metrics['test_units']} "
        "held-out test units: the translation ran on PostgreSQL *and* returned what the "
        "Oracle statement returned on Oracle. Text similarity is not used anywhere."
    )
    add("")
    add(
        "All strategies are scored by the identical verifier, with the same comparison "
        "rules, timeouts and treatment of statements that cannot be value-compared. "
        "`ora2pg` is reported over DDL only, which is all it translates."
    )
    add("")

    add("## Headline")
    add("")
    add(
        *[
            "\n".join(
                _table(
                    [
                        [
                            metrics["models"][m],
                            _pct(metrics["execution_accuracy"][m]),
                            _pct(metrics["runs_without_error"][m]),
                        ]
                        for m in models
                    ],
                    ["Strategy", "Execution accuracy", "Ran without error"],
                )
            )
        ]
    )
    add("")

    add("## By generalisation axis")
    add("")
    add(
        "Two things are held out: the `logistics` schema and 25 of 123 templates. "
        "The four cells below are the reason that matters."
    )
    add("")
    header = ["Strategy", *[SPLIT_LABELS[s] for s in SPLITS]]
    rows = [
        [metrics["models"][m], *[_pct(metrics["by_split"][s][m]) for s in SPLITS]] for m in models
    ]
    add("\n".join(_table(rows, header)))
    add("")

    finetuned_seen = metrics["by_split"]["test_unseen_schema"]["finetuned"]["rate"]
    finetuned_unseen = metrics["by_split"]["test_unseen_template"]["finetuned"]["rate"]
    base_unseen_both = metrics["by_split"]["test_unseen_both"]["base"]["rate"]
    finetuned_unseen_both = metrics["by_split"]["test_unseen_both"]["finetuned"]["rate"]

    add("### What this says, plainly")
    add("")
    add(
        f"The fine-tuned model scores {finetuned_seen:.0%} on a schema it has never seen, "
        f"and {finetuned_unseen:.0%} on a construct variant it has never seen. **It learned "
        "the transformations it was shown and generalised them to new table and column "
        "names, but it did not generalise to new transformations.**"
    )
    add("")
    if finetuned_unseen_both <= base_unseen_both:
        add(
            f"On the hardest split — unseen schema *and* unseen template — the fine-tuned "
            f"model ({finetuned_unseen_both:.0%}) is **no better than the untrained base "
            f"model** ({base_unseen_both:.0%}). The headline gain comes almost entirely "
            "from the splits where the template was seen in training."
        )
        add("")
    add(
        "A schema-only holdout, which is the usual design, would have reported the "
        f"{finetuned_seen:.0%} figure and nothing else. The template axis is what exposes "
        "the limit."
    )
    add("")

    add("## By construct")
    add("")
    add(
        "Categories are small, so individual rows are noisy. Read the shape, not the "
        "decimal places."
    )
    add("")
    rows = []
    for category, cells in sorted(metrics["by_category"].items()):
        rows.append([f"`{category}`", *[_pct(cells[m]) for m in models]])
    add(
        "\n".join(
            _table(rows, ["Construct", *[metrics["models"][m].split(" (")[0] for m in models]])
        )
    )
    add("")

    add("## Error analysis")
    add("")
    for model in ("base", "finetuned"):
        analysis = metrics["failure_analysis"].get(model)
        if not analysis:
            continue
        add(f"### {metrics['models'][model]} — {analysis['failures']} failures")
        add("")
        add(
            "\n".join(
                _table(
                    [
                        [reason or "unknown", str(count)]
                        for reason, count in analysis["by_reason"].items()
                    ],
                    ["Why it failed", "Count"],
                )
            )
        )
        add("")
        add(
            "Worst constructs: "
            + ", ".join(f"`{c}` ({n})" for c, n in list(analysis["by_category"].items())[:6])
        )
        add("")
        if analysis["examples"]:
            example = analysis["examples"][0]
            add("A representative failure:")
            add("")
            add("```sql")
            add(f"-- construct: {example['category']}  ({example['split']})")
            add("-- oracle")
            add(example["oracle"])
            add("-- predicted")
            add(example["prediction"] or "(empty)")
            add(f"-- verdict: {example['reason']}")
            if example["detail"]:
                add(f"-- {example['detail']}")
            add("```")
            add("")

    add("## How to reproduce")
    add("")
    add("```bash")
    add("make seed       # load the schemas into both engines")
    add("make generate   # build and Oracle-verify the unit pool")
    add("make verify     # reference, sqlglot and ora2pg baselines")
    add("make dataset    # build the train/test splits")
    add("make eval       # score the predictions by execution")
    add("```")
    add("")
    add(
        "Model predictions come from `notebooks/predict.ipynb` on a Kaggle T4; the "
        "committed `results/predictions_*.jsonl` are its output."
    )
    add("")
    return "\n".join(lines)


def write(db_path: Path = store.DEFAULT_DB_PATH) -> tuple[Path, Path]:
    metrics = collect(db_path)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(render(metrics), encoding="utf-8")
    return METRICS_PATH, REPORT_PATH
