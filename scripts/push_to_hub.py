"""Push the built dataset to the HuggingFace Hub.

NOT TESTED FROM THE MACHINE THIS WAS WRITTEN ON: that network returns 403 for
huggingface.co, so neither the upload nor the `datasets` dependency could be
exercised. Run it from Kaggle or any network with Hub access.

    pip install "datasets>=3.0" "huggingface_hub>=0.26"
    export HF_TOKEN=...            # a write token
    python scripts/push_to_hub.py --repo-id <your-username>/orashift-pairs

Add --private to keep the dataset unlisted while you check it over.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_DATA_DIR = Path("data/dataset")
SPLIT_FILES = (
    "train",
    "val",
    "test_in_schema",
    "test_unseen_schema",
    "test_unseen_template",
    "test_unseen_both",
)


def load_split(data_dir: Path, name: str) -> list[dict]:
    path = data_dir / f"{name}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing; run `orashift build-dataset` first")
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", required=True, help="e.g. your-username/orashift-pairs")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()

    token = os.environ.get("HF_TOKEN")
    if not token:
        print(
            "HF_TOKEN is not set. Create a write token at https://huggingface.co/settings/tokens",
            file=sys.stderr,
        )
        return 2

    try:
        from datasets import Dataset, DatasetDict
        from huggingface_hub import HfApi
    except ImportError:
        print(
            'Missing dependencies. Run: pip install "datasets>=3.0" "huggingface_hub>=0.26"',
            file=sys.stderr,
        )
        return 2

    splits = {}
    for name in SPLIT_FILES:
        rows = load_split(args.data_dir, name)
        if rows:
            splits[name] = Dataset.from_list(rows)
            print(f"  {name}: {len(rows)} examples")

    if not splits:
        print("nothing to push", file=sys.stderr)
        return 1

    DatasetDict(splits).push_to_hub(args.repo_id, token=token, private=args.private)
    print(f"pushed splits to https://huggingface.co/datasets/{args.repo_id}")

    card = args.data_dir / "README.md"
    if card.exists():
        HfApi().upload_file(
            path_or_fileobj=str(card),
            path_in_repo="README.md",
            repo_id=args.repo_id,
            repo_type="dataset",
            token=token,
        )
        print("uploaded the dataset card")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
