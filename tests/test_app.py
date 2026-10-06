"""The demo's routing logic.

The app cannot execute anything, so its only real decision is which path to send
a statement down. That decision is derived from measured per-construct accuracy,
and these tests pin it to the measurement.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.translate import ORACLE_ONLY, needs_model, translate, try_sqlglot

METRICS = Path("results/metrics.json")

# sqlglot scores 100% on these, so routing them to the model would be wasteful
# and would wrongly flag correct output as unreliable.
RULES_HANDLE = [
    "SELECT NVL(commission_pct, 0) FROM hr_employees",
    "SELECT DECODE(status, 'PAID', 1, 0) FROM retail_orders",
    "SELECT UPPER(full_name), SUBSTR(full_name, 1, 3) FROM retail_customers",
    "SELECT a FROM t WHERE x IN (SELECT y FROM u)",
    "WITH c AS (SELECT 1 AS n FROM t) SELECT n FROM c",
    "SELECT department_id, COUNT(*) FROM hr_employees GROUP BY department_id",
]

# sqlglot scores 0-8% on these; they must reach the model.
MODEL_NEEDED = [
    "SELECT employee_id FROM hr_employees WHERE ROWNUM <= 5",
    "SELECT a FROM t START WITH p IS NULL CONNECT BY PRIOR a = p",
    "SELECT TRUNC(order_date, 'MM') FROM retail_orders",
    "SELECT ADD_MONTHS(hire_date, 3) FROM hr_employees",
    "SELECT COUNT(*) FROM t WHERE d < SYSDATE",
    "SELECT 7/2 FROM dual",
    "SELECT seq.NEXTVAL FROM dual",
]


@pytest.mark.parametrize("sql", RULES_HANDLE)
def test_constructs_sqlglot_handles_stay_on_the_rule_path(sql: str):
    assert needs_model(sql) == [], sql
    assert translate(sql).path == "sqlglot"


@pytest.mark.parametrize("sql", MODEL_NEEDED)
def test_constructs_sqlglot_fails_are_routed_to_the_model(sql: str):
    assert needs_model(sql), sql


def test_routing_is_flagged_when_the_model_is_unavailable():
    """It must not present a rule guess as a confident answer."""
    result = translate("SELECT employee_id FROM hr_employees WHERE ROWNUM <= 5")
    assert "unreliable" in result.path
    assert "verify" in result.note.lower()


def test_empty_input_is_handled():
    assert translate("").path == "failed"
    assert translate("   ").path == "failed"


def test_trailing_semicolon_is_tolerated():
    assert translate("SELECT 1 FROM t;").postgres_sql


def test_sqlglot_actually_rewrites_what_it_claims_to():
    assert "COALESCE" in (try_sqlglot("SELECT NVL(a, 0) FROM t") or "")
    assert "CASE" in (try_sqlglot("SELECT DECODE(a, 1, 'x', 'y') FROM t") or "")


def test_routing_tokens_are_lowercase():
    """needs_model lowercases its input, so an uppercase token would never match."""
    for token in ORACLE_ONLY:
        assert token == token.lower(), token


def test_detection_is_case_insensitive():
    assert needs_model("select * from DUAL")
    assert needs_model("SELECT x FROM t WHERE rownum <= 1")


@pytest.mark.skipif(not METRICS.exists(), reason="metrics.json not built")
def test_routing_matches_the_measured_accuracy():
    """Every construct sqlglot fails badly on must have a detection token."""
    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    tokens = " ".join(ORACLE_ONLY)
    hints = {
        "rownum": "rownum",
        "connect_by": "connect by",
        "trunc_date": "trunc(",
        "add_months": "add_months",
        "pivot": "pivot",
        "merge": "merge",
        "dual": "dual",
        "sequence": "nextval",
        "sysdate": "sysdate",
        "listagg": "listagg",
    }
    for category, cells in metrics["by_category"].items():
        cell = cells.get("sqlglot")
        if not cell or not cell["total"] or cell["rate"] > 0.85:
            continue
        hint = hints.get(category)
        if hint:
            assert hint in tokens, f"{category} scores {cell['rate']:.0%} but has no token"
