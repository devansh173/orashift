"""Assemble the static HuggingFace Space in space/.

The Space is a single static page: the rule path runs in the visitor's browser
under Pyodide, using the same routing as `orashift translate` and the Gradio demo, and
the fine-tuned model is shown through its real test-set outputs rather than run
live. Everything it displays is read from committed results files.

    uv run python scripts/build_space.py
    hf upload <user>/orashift space . --repo-type space
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

SPACE_DIR = Path("space")
RESULTS = Path("results")


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def build_units() -> list[dict]:
    base = {row["unit_key"]: row for row in load_jsonl(RESULTS / "predictions_base.jsonl")}
    tuned = load_jsonl(RESULTS / "predictions_finetuned.jsonl")
    units = []
    for row in tuned:
        units.append(
            {
                "key": row["unit_key"],
                "split": row["split"],
                "category": row["category"],
                "schema": row["schema"],
                "oracle": row["oracle_sql"],
                "reference": row["reference_sql"],
                "base": base[row["unit_key"]]["prediction"],
                "finetuned": row["prediction"],
            }
        )
    return units


def build_metrics() -> dict:
    metrics = json.loads((RESULTS / "metrics.json").read_text(encoding="utf-8"))
    keep = ("execution_accuracy", "runs_without_error", "by_split", "split_labels")
    out = {key: metrics[key] for key in keep}
    out["models"] = metrics["models"]
    out["by_category"] = metrics["by_category"]
    return out


def main() -> int:
    SPACE_DIR.mkdir(exist_ok=True)
    shutil.copyfile("src/orashift/translate.py", SPACE_DIR / "translate.py")
    payload = {"units": build_units(), "metrics": build_metrics()}
    target = SPACE_DIR / "data.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), "utf-8")
    print(f"wrote {target} ({target.stat().st_size // 1024} KB, {len(payload['units'])} units)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
