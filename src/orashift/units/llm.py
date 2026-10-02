"""Optional LLM-generated units, for variety the templates cannot reach.

Off by default. Templates already cover every construct on the project's list,
and they do it deterministically and for free; this path exists to widen the
*phrasing* of those constructs, which matters for a model that will see real
human-written SQL.

It targets any OpenAI-compatible chat-completions endpoint, so the same code
works against OpenAI, Groq, Together, OpenRouter, or a local Ollama or vLLM
server. Nothing here is trusted either: generated statements go through exactly
the same Oracle execution filter as template ones, so a hallucinated function
is dropped rather than poisoning the dataset.

Only the network call is unexercised by the test suite. Prompt construction and
response parsing are pure functions and are tested.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from orashift.config import Settings
from orashift.logging import get_logger
from orashift.units.anchors import ANCHORS
from orashift.units.dedupe import normalize
from orashift.units.types import Category, Source, Unit, UnitType

log = get_logger(__name__)

DDL_ROOT = Path("sql/schemas/oracle")

SYSTEM_PROMPT = (
    "You write Oracle SQL. You are given a schema and an Oracle construct. "
    "Produce standalone SELECT statements that exercise that construct against "
    "that schema.\n"
    "Rules:\n"
    "- Oracle dialect only. The statements must run on Oracle 23c or newer.\n"
    "- Use only the tables and columns given. Do not invent any.\n"
    "- Read-only SELECT statements. No DDL, no DML, no PL/SQL.\n"
    "- Deterministic results: always ORDER BY when returning more than one row, "
    "and do not use SYSDATE or sequences in the select list.\n"
    "- One statement per line, no trailing semicolon, no commentary, no markdown."
)

_FENCE = re.compile(r"^```(?:sql)?\s*|\s*```$", re.MULTILINE)
_LEADING_NUMBER = re.compile(r"^\s*\d+[.)]\s*")


def schema_ddl(schema_name: str) -> str:
    """The Oracle DDL for one schema, used as prompt context."""
    return (DDL_ROOT / f"{schema_name}.sql").read_text(encoding="utf-8")


def build_messages(schema_name: str, category: Category, count: int) -> list[dict[str, str]]:
    """The chat messages for one (schema, construct) request."""
    anchors = ANCHORS[schema_name]
    user = (
        f"Schema `{schema_name}`, defined as:\n\n```sql\n{schema_ddl(schema_name)}\n```\n\n"
        f"Write {count} different Oracle SELECT statements that each use "
        f"the `{category.value}` construct against this schema.\n"
        f"Vary the tables, the columns and the shape of the query between them.\n"
        f"Useful starting points in this schema: "
        f"{anchors.fact}, {anchors.dim or anchors.fact}."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def parse_statements(content: str) -> list[str]:
    """Pull individual statements out of a model response.

    Tolerant on purpose: models wrap SQL in fences, number their lists, and
    add trailing semicolons regardless of instructions.
    """
    cleaned = _FENCE.sub("", content).strip()
    statements: list[str] = []
    for line in cleaned.splitlines():
        candidate = _LEADING_NUMBER.sub("", line).strip().rstrip(";").strip()
        if not candidate or candidate.startswith("--"):
            continue
        if not candidate.upper().startswith(("SELECT", "WITH")):
            continue
        statements.append(" ".join(candidate.split()))
    return statements


def _post(settings: Settings, messages: list[dict[str, str]]) -> str:
    payload = json.dumps(
        {
            "model": settings.unit_llm_model,
            "messages": messages,
            "temperature": 0.8,
        }
    ).encode("utf-8")
    # The URL comes from this project's own settings, not from user input.
    request = urllib.request.Request(
        f"{settings.unit_llm_base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.unit_llm_api_key.get_secret_value()}",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read())
    return body["choices"][0]["message"]["content"]


def generate_units(
    settings: Settings,
    categories: list[Category],
    schemas: list[str] | None = None,
) -> list[Unit]:
    """Ask the configured model for statements. Returns [] when disabled."""
    if not settings.unit_llm_enabled:
        log.info("llm_generation_disabled")
        return []

    target_schemas = schemas or list(ANCHORS)
    units: list[Unit] = []

    for schema_name in target_schemas:
        for category in categories:
            messages = build_messages(schema_name, category, settings.unit_llm_per_category)
            try:
                content = _post(settings, messages)
            except (urllib.error.URLError, KeyError, json.JSONDecodeError) as exc:
                log.error(
                    "llm_request_failed", schema=schema_name, category=str(category), error=str(exc)
                )
                continue

            for sql in parse_statements(content):
                normalized, _parsed = normalize(sql)
                units.append(
                    Unit(
                        unit_key=_key(normalized),
                        schema_name=schema_name,
                        unit_type=UnitType.QUERY,
                        category=category,
                        sql_text=sql,
                        source=Source.LLM,
                        normalized_sql=normalized,
                        metadata={"model": settings.unit_llm_model},
                    )
                )
            log.info("llm_generated", schema=schema_name, category=str(category), count=len(units))
    return units


def _key(normalized_sql: str) -> str:
    return hashlib.sha256(normalized_sql.encode("utf-8")).hexdigest()[:16]
