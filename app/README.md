# Demo

A Gradio app: paste Oracle SQL, get PostgreSQL back, and see **which path produced it**.

## Running it locally

```bash
uv sync --extra demo
uv run python app/app.py          # http://127.0.0.1:7860
```

Works immediately with no model. The rule path answers most statements, and anything
needing the model is answered by the rules *and flagged as unverified* rather than
silently presented as correct.

To enable the model fallback:

```bash
export DEMO_ADAPTER=/path/to/orashift-qlora-adapter   # or a Hub repo id
uv run python app/app.py
```

## Why rules first

It is not a demo shortcut — it is the strategy that scored best in evaluation (87%, against
the fine-tuned model's 86% and sqlglot's 61%). It also makes the demo usable on a free CPU:
most statements never reach the model, so they return instantly, and only the
Oracle-specific ones pay for a generation.

## Which constructs go to the model

That routing is **derived from `results/metrics.json`**, not from intuition. The first
version of the list was written from memory and sent `NVL` and `DECODE` to the model, which
was wrong — sqlglot scores 100% on both.

| Routed to the model | sqlglot's measured accuracy |
| --- | ---: |
| `ROWNUM`, `CONNECT BY`, `TRUNC(date)`, `ADD_MONTHS`, `PIVOT`, `MERGE`, `DUAL`, `NEXTVAL`, DDL | 0% |
| `SYSDATE` | 8% |
| `LISTAGG` | 60% |
| `UPDATE`, `(+)` joins | 67–71% |
| `\|\|` concatenation | 83% |

| Left to the rules | |
| --- | ---: |
| `NVL`, `DECODE`, `TO_CHAR`, string functions, analytics, subqueries, CTEs, aggregates | 100% |
| `FETCH FIRST` | 98% |
| `MINUS` | 86% |

The threshold is deliberately cautious. The demo cannot execute anything, so it cannot tell
good rule output from bad; where the rules are only *usually* right, a slower answer beats
a confidently wrong one.

## Performance on free CPU

A 3B model in fp32 on CPU takes roughly 10–30 seconds per translation. Most inputs never
reach it. If that is still too slow for your deployment, in rough order of effort:

1. **Keep rules first** — already the default, and the single biggest win.
2. **Quantise to GGUF and serve with `llama.cpp`** — 4-bit on CPU is several times faster
   than fp32 transformers, at a small quality cost.
3. **Use a smaller base** — a 1.5B coder model would roughly halve latency; the adapter
   would need retraining.
4. **Put it on a GPU Space** — sub-second, but no longer free.

## Deploying to HuggingFace Spaces

```bash
pip install huggingface_hub
huggingface-cli login
huggingface-cli repo create orashift --type space --space_sdk gradio
# copy app/, results/metrics.json and a requirements.txt into the Space repo
```

Set `DEMO_ADAPTER` as a Space secret to enable the model path.

**Not tested from this repository's development machine**, whose network blocks
`huggingface.co`. The app itself runs locally; only the Spaces upload is unverified.
