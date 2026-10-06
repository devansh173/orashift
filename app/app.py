"""Gradio demo: paste Oracle SQL, get PostgreSQL back, and see which path produced it.

Run locally:

    uv sync --extra demo
    uv run python app/app.py

The model is optional. Set DEMO_ADAPTER to a local adapter directory or a Hub
repo id to enable the fallback path; without it the rule path still answers most
statements and the UI says plainly when it is guessing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import gradio as gr

# Import works whether this is run as `python app/app.py`, as `python -m app.app`,
# or from a HuggingFace Space where app.py sits at the repository root.
try:
    from app.translate import ADAPTER, translate
except ImportError:  # pragma: no cover - depends on how it was launched
    from translate import ADAPTER, translate

METRICS = Path("results/metrics.json")

EXAMPLES = [
    ["SELECT employee_id, last_name FROM hr_employees WHERE ROWNUM <= 5", ""],
    ["SELECT NVL(commission_pct, 0) AS commission FROM hr_employees ORDER BY employee_id", ""],
    [
        "SELECT category_id, category_name, LEVEL AS lvl\n"
        "FROM retail_categories\n"
        "START WITH parent_category_id IS NULL\n"
        "CONNECT BY PRIOR category_id = parent_category_id\n"
        "ORDER BY category_id",
        "",
    ],
    [
        "SELECT TRUNC(order_date, 'MM') AS month, COUNT(*) FROM retail_orders\n"
        "GROUP BY TRUNC(order_date, 'MM') ORDER BY month",
        "",
    ],
    ["SELECT shipment_id, ADD_MONTHS(dispatched_at, 3) FROM logistics_shipments", ""],
    ["SELECT 7/2 AS half FROM dual", ""],
]


def _headline() -> str:
    if not METRICS.exists():
        return ""
    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    accuracy = metrics["execution_accuracy"]
    rows = [
        ("Hybrid (this demo)", accuracy["hybrid"]),
        ("Fine-tuned model", accuracy["finetuned"]),
        ("Base model", accuracy["base"]),
        ("sqlglot alone", accuracy["sqlglot"]),
    ]
    lines = ["| Strategy | Execution accuracy |", "| --- | ---: |"]
    lines += [
        f"| {name} | {cell['verified']}/{cell['total']} ({cell['rate']:.0%}) |"
        for name, cell in rows
    ]
    return "\n".join(lines)


def on_translate(oracle_sql: str, schema_context: str) -> tuple[str, str]:
    result = translate(oracle_sql, schema_context)
    if result.path == "failed":
        return "", f"**Could not translate.** {result.note}"

    icon = {"sqlglot": "rules", "fine-tuned model": "model"}.get(result.path, "rules")
    banner = f"**Path: {result.path}** ({icon}) — {result.note}"
    if "unreliable" in result.path:
        banner = f"⚠️ {banner}"
    return result.postgres_sql, banner


def build() -> gr.Blocks:
    model_state = (
        f"Model fallback enabled (`{ADAPTER}`)."
        if ADAPTER
        else "Model fallback **not** enabled: set `DEMO_ADAPTER` to switch it on. "
        "Statements needing it are answered by the rules and flagged as unverified."
    )

    with gr.Blocks(title="OraShift — Oracle SQL to PostgreSQL") as demo:
        gr.Markdown(
            "# OraShift\n"
            "### Oracle SQL to PostgreSQL, judged by execution\n\n"
            "Rules first, fine-tuned model second. That ordering is not arbitrary: it "
            "scored best in evaluation, and it means most statements return instantly "
            "because they never reach the model.\n\n"
            "Every number below came from **executing** translations against real Oracle "
            "and PostgreSQL databases and comparing the results — never from text "
            "similarity.\n\n"
            f"{model_state}"
        )

        with gr.Row():
            with gr.Column(scale=1):
                oracle_input = gr.Code(
                    label="Oracle SQL",
                    language="sql",
                    lines=10,
                    value=EXAMPLES[0][0],
                )
                schema_input = gr.Textbox(
                    label="Table definitions (optional)",
                    placeholder="CREATE TABLE hr_employees (...);",
                    lines=4,
                    info="Helps the model when column types matter. Ignored by the rules.",
                )
                go = gr.Button("Translate", variant="primary")
            with gr.Column(scale=1):
                postgres_output = gr.Code(label="PostgreSQL", language="sql", lines=10)
                path_output = gr.Markdown()

        gr.Examples(
            examples=EXAMPLES,
            inputs=[oracle_input, schema_input],
            label="Try one of these",
        )

        headline = _headline()
        if headline:
            gr.Markdown(
                f"## Measured results\n\n{headline}\n\n"
                "Over 330 held-out test units. Full breakdown in `results/report.md`."
            )

        gr.Markdown(
            "### Honest limitations\n"
            "- The fine-tune generalises to **unseen schemas** (99%) but not to **unseen "
            "constructs** (70%). On statements using a construct variant it never saw, it "
            "is no better than the untrained base model.\n"
            "- Training data is synthetic and template-generated, so its phrasing is more "
            "uniform than real-world SQL.\n"
            "- This demo cannot execute anything, so it cannot verify its own output. "
            "The accuracy figures come from the offline evaluation, not from your input."
        )

        # gr.Code has no submit event, so the button is the only trigger.
        go.click(on_translate, [oracle_input, schema_input], [postgres_output, path_output])
    return demo


if __name__ == "__main__":
    build().launch(
        server_name=os.environ.get("GRADIO_SERVER_NAME", "127.0.0.1"),
        server_port=int(os.environ.get("GRADIO_SERVER_PORT", "7860")),
        share=False,
    )
