"""The hybrid translation path, shared by the demo and testable without a GPU.

Rules first, model second. That ordering is not a demo convenience: it is the
strategy that scored best in evaluation (87% against the fine-tuned model's 86%),
because `sqlglot` is free, instant and deterministic, and the model only has to
handle what rules cannot.

It also makes the demo usable on a free CPU. Most statements never reach the
model at all, so they return immediately; only the Oracle-specific ones pay for
a generation.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import sqlglot
from sqlglot.errors import ParseError, TokenError, UnsupportedError

logging.getLogger("sqlglot").setLevel(logging.ERROR)

BASE_MODEL = os.environ.get("DEMO_BASE_MODEL", "Qwen/Qwen2.5-Coder-3B-Instruct")
ADAPTER = os.environ.get("DEMO_ADAPTER", "")
MAX_NEW_TOKENS = 448

SYSTEM_PROMPT = """You translate Oracle SQL into PostgreSQL.

Rules:
- Return only the PostgreSQL statement. No explanation, no markdown, no semicolon.
- The translation must run on PostgreSQL 17 and return exactly what the Oracle
  statement returns on Oracle.
- Oracle types map as: NUMBER(p,0) to smallint/integer/bigint by precision,
  NUMBER(p,s) to numeric(p,s), VARCHAR2(n) to varchar(n), CHAR(n) to char(n),
  CLOB to text, DATE to timestamp(0).
- Watch the semantics, not just the syntax: an Oracle DATE carries a time,
  '' is NULL in Oracle, concatenating NULL yields the other operand in Oracle
  but NULL in PostgreSQL, and integer division truncates in PostgreSQL."""

# Which constructs get routed to the model.
#
# Derived from results/metrics.json, not from intuition. A first version of this
# list was written from memory and sent NVL and DECODE to the model, which was
# wrong: sqlglot scores 100% on both. The measured per-construct accuracy is:
#
#   routed to the model (sqlglot <= 83%):
#     rownum 0%, connect_by 0%, trunc_date 0%, add_months 0%, pivot 0%,
#     merge 0%, dual 0%, sequence 0%, DDL table/constraint/index 0%,
#     sysdate 8%, listagg 60%, dml_update 67%, outer_join_plus 71%,
#     null_concat 83%
#
#   left to the rules (sqlglot >= 86%):
#     nvl 100%, decode 100%, to_char_date 100%, string_func 100%,
#     analytic 100%, subquery 100%, cte 100%, aggregate 100%,
#     fetch_first 98%, minus 86%
#
# The threshold is deliberately cautious. The demo cannot execute anything, so
# it cannot tell a good rule output from a bad one; where the rules are only
# usually right, a slower answer beats a confidently wrong one.
ORACLE_ONLY = (
    "rownum",
    "connect by",
    "start with",
    "sys_connect_by_path",
    "connect_by_root",
    "connect_by_isleaf",
    "trunc(",
    "add_months",
    "months_between",
    "last_day",
    "sysdate",
    "systimestamp",
    "pivot",
    "unpivot",
    "merge into",
    "from dual",
    ".nextval",
    ".currval",
    "listagg",
    "(+)",
    "||",
    "update ",
    "varchar2",
    "number(",
    "clob",
)


@dataclass(frozen=True, slots=True)
class Translation:
    postgres_sql: str
    path: str
    """Which route produced it: 'sqlglot', 'fine-tuned model', or 'failed'."""
    note: str = ""


def needs_model(oracle_sql: str) -> list[str]:
    """Oracle-only constructs present in the statement, if any."""
    lowered = f" {' '.join(oracle_sql.lower().split())} "
    return [token.strip() for token in ORACLE_ONLY if token in lowered]


def try_sqlglot(oracle_sql: str) -> str | None:
    try:
        converted = sqlglot.transpile(oracle_sql, read="oracle", write="postgres")
    except (ParseError, TokenError, UnsupportedError, RecursionError, ValueError, KeyError):
        return None
    if not converted or not converted[0].strip():
        return None
    return converted[0].strip()


@lru_cache(maxsize=1)
def load_model() -> tuple[Any, Any] | None:
    """Load the fine-tuned model once, or return None if it is unavailable.

    The demo must still work without it: the rule path handles most statements,
    and a demo that refuses to start because a 6 GB download failed is worse
    than one that is honest about which half is running.
    """
    if not ADAPTER:
        return None
    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError:
        return None

    try:
        tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
        model = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL, torch_dtype=torch.float32, device_map="cpu"
        )
        model = PeftModel.from_pretrained(model, ADAPTER)
        model.eval()
        return model, tokenizer
    except Exception:
        return None


def run_model(oracle_sql: str, schema_context: str = "") -> str | None:
    loaded = load_model()
    if loaded is None:
        return None
    model, tokenizer = loaded

    system = SYSTEM_PROMPT
    if schema_context.strip():
        system = f"{system}\n\nOracle table definitions:\n\n{schema_context.strip()}"

    prompt = tokenizer.apply_chat_template(
        [{"role": "system", "content": system}, {"role": "user", "content": oracle_sql.strip()}],
        tokenize=False,
        add_generation_prompt=True,
    )
    import torch

    inputs = tokenizer(prompt, return_tensors="pt")
    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )
    generated = output[0][inputs["input_ids"].shape[1] :]
    return tokenizer.decode(generated, skip_special_tokens=True).strip()


def translate(oracle_sql: str, schema_context: str = "") -> Translation:
    """Rules first, model as fallback. Returns the result and which path produced it."""
    oracle_sql = (oracle_sql or "").strip().rstrip(";")
    if not oracle_sql:
        return Translation("", "failed", "Nothing to translate.")

    oracle_isms = needs_model(oracle_sql)
    rule_output = try_sqlglot(oracle_sql)

    if rule_output and not oracle_isms:
        return Translation(rule_output, "sqlglot", "No Oracle-specific constructs found.")

    model_output = run_model(oracle_sql, schema_context)
    if model_output:
        found = ", ".join(f"`{t}`" for t in oracle_isms[:4]) or "an unsupported construct"
        return Translation(model_output, "fine-tuned model", f"Rules cannot handle {found}.")

    if rule_output:
        found = ", ".join(f"`{t}`" for t in oracle_isms[:4])
        return Translation(
            rule_output,
            "sqlglot (unreliable here)",
            f"The model is not loaded, and this statement contains {found}, "
            "which sqlglot usually passes through unchanged. Verify before using.",
        )

    return Translation("", "failed", "Neither path could translate this statement.")
