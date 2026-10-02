"""Generate the dataset card.

Every number in the card is read from the build report, which is read from the
database. Nothing is typed in by hand, so the card cannot drift away from the
files it describes.
"""

from __future__ import annotations

from pathlib import Path

from orashift.catalog import HELD_OUT_SCHEMA, SCHEMAS
from orashift.dataset.build import CHARS_PER_TOKEN, MAX_SEQ_LENGTH, BuildReport
from orashift.dataset.split import Split
from orashift.units.templates import ALL_TEMPLATES, HELD_OUT_TEMPLATES

SPLIT_DESCRIPTIONS = {
    Split.TRAIN: "Training. Seen schemas, seen templates.",
    Split.VAL: "Validation, carved from the same bucket as training.",
    Split.TEST_IN_SCHEMA: "Test. Seen schema, seen template: the easiest case.",
    Split.TEST_UNSEEN_SCHEMA: "Test. Held-out `logistics` schema, template seen in training.",
    Split.TEST_UNSEEN_TEMPLATE: "Test. Seen schema, construct variant never trained on.",
    Split.TEST_UNSEEN_BOTH: "Test. Held-out schema and held-out template: the hardest case.",
}


def render(report: BuildReport) -> str:
    """The dataset card as markdown."""
    lines: list[str] = []
    add = lines.append

    add("# OraShift translation pairs")
    add("")
    add("Oracle SQL to PostgreSQL translation pairs, **every one verified by execution**:")
    add("the Oracle statement was run on Oracle, the PostgreSQL statement on PostgreSQL,")
    add("and the results compared. A pair is only present if they matched.")
    add("")
    add("Measured against **Oracle AI Database 26ai Free 23.26.2.0.0** and")
    add("**PostgreSQL 17.10**. Both the data and the schemas are synthetic.")
    add("")

    add("## Splits")
    add("")
    add("| Split | Examples | What it measures |")
    add("| --- | ---: | --- |")
    for split in Split:
        add(f"| `{split}` | {report.counts.get(str(split), 0)} | {SPLIT_DESCRIPTIONS[split]} |")
    add(f"| **total** | **{report.total}** | |")
    add("")

    add("## Why there are four test sets")
    add("")
    add("Holding out one schema measures less than it appears to. If a template is seen")
    add("during training as `retail` and tested as `logistics`, the model has already met")
    add("that exact translation pattern and only the table names are new -- that tests")
    add("vocabulary robustness, not translation skill.")
    add("")
    add(f"So two things are withheld: the whole **`{HELD_OUT_SCHEMA}`** schema, and")
    add(f"**{len(HELD_OUT_TEMPLATES)} of {len(ALL_TEMPLATES)}** templates. Reporting the")
    add("resulting four cells separately shows which kind of generalisation actually holds.")
    add("")

    add("## Format")
    add("")
    add("Chat JSONL, one example per line:")
    add("")
    add("```json")
    add('{"messages": [')
    add('  {"role": "system", "content": "task rules + the Oracle DDL this statement uses"},')
    add('  {"role": "user", "content": "<Oracle statement>"},')
    add('  {"role": "assistant", "content": "<PostgreSQL statement>"}')
    add('], "meta": {"schema": "...", "category": "...", "unit_type": "..."}}')
    add("```")
    add("")
    add("The system prompt carries only the table definitions the statement actually")
    add("references, not the whole schema: the rest would be spent token budget.")
    add("The assistant turn is the translation alone, with no explanation, so loss on")
    add("assistant tokens trains exactly the output wanted at inference.")
    add("")

    add("## Coverage")
    add("")
    add("| Category | " + " | ".join(str(s) for s in Split) + " |")
    add("| --- | " + " | ".join("---:" for _ in Split) + " |")
    for category in sorted(report.per_category):
        row = report.per_category[category]
        add(f"| `{category}` | " + " | ".join(str(row.get(str(s), 0)) for s in Split) + " |")
    add("")

    add("## Honest limitations")
    add("")
    if report.thin_categories:
        add("**Thin categories.** These have fewer than 10 training examples, so any")
        add("per-category result for them is noisy and should not be read as a trend:")
        add("")
        for category, count in report.thin_categories:
            add(f"- `{category}`: {count} training examples")
        add("")
    add("**DDL and DML are under-represented** relative to queries, because growing the")
    add("pool by widening template parameters multiplies query variants far more than it")
    add("multiplies schema statements.")
    add("")
    add("**The translations are one person's style.** Each is execution-verified, so it is")
    add("correct, but it is one correct style among several. A model trained on it may be")
    add("more brittle to alternative phrasings than the accuracy figures suggest.")
    add("")
    add("**The statements are template-generated**, so their phrasing is more uniform than")
    add("human-written SQL.")
    add("")
    add("**Token lengths here are estimates, not measurements.** They assume")
    add(f"{CHARS_PER_TOKEN} characters per token, which over-counts for SQL, so the filter")
    add("errs towards excluding. The real tokenizer could not be run on the machine that")
    add("built this dataset, because its network blocks huggingface.co. The training")
    add("notebook re-measures with the real tokenizer and reports the true exclusions.")
    add("")
    add(f"- Longest example: ~{report.longest} estimated tokens")
    add(f"- Budget: {MAX_SEQ_LENGTH} tokens")
    add(f"- Excluded as too long: {report.excluded}")
    add("")

    add("## Source schemas")
    add("")
    add("| Schema | Tables | Role |")
    add("| --- | ---: | --- |")
    for name, schema in SCHEMAS.items():
        role = "held out entirely" if name == HELD_OUT_SCHEMA else "training"
        add(f"| `{name}` | {len(schema.tables)} | {role} |")
    add("")

    add("## Licence")
    add("")
    add("MIT. All schemas and data are synthetic; no proprietary SQL is included.")
    add("")
    return "\n".join(lines)


def write(report: BuildReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(report), encoding="utf-8")
    return path
