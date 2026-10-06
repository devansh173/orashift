---
title: OraShift
emoji: 🔁
colorFrom: red
colorTo: blue
sdk: static
app_file: index.html
pinned: false
license: mit
short_description: Oracle SQL to PostgreSQL with a QLoRA fine-tuned LLM
models:
  - devansh173/orashift-qlora-adapter
  - Qwen/Qwen2.5-Coder-3B-Instruct
datasets:
  - devansh173/orashift-pairs
---

# OraShift demo

Oracle SQL to PostgreSQL with a QLoRA fine-tune of Qwen2.5-Coder-3B, judged by
**executing** every translation on real Oracle and PostgreSQL databases.

This is a static page. The `sqlglot` rule path runs live in your browser under
Pyodide, using the project's own routing code. The 3B model is not run here: for
statements in the held-out test set, the page shows the model's real outputs from
the evaluation run, next to the base model and the execution-verified reference.

- Code and full write-up: https://github.com/devansh173/orashift
- Adapter: https://huggingface.co/devansh173/orashift-qlora-adapter
- Dataset: https://huggingface.co/datasets/devansh173/orashift-pairs

Built by `scripts/build_space.py` in the repository.
