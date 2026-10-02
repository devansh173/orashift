"""Build the chat messages for one training example.

The system prompt carries the Oracle table definitions the statement actually
references. Including the whole schema would waste most of the token budget on
tables the statement never mentions, and including nothing would ask the model
to translate column references it cannot see.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from orashift.catalog import SCHEMAS

DDL_ROOT = Path("sql/schemas/oracle")

SYSTEM_PREAMBLE = """You translate Oracle SQL into PostgreSQL.

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

_CREATE_TABLE = re.compile(
    r"^CREATE\s+TABLE\s+(\w+)\s*\((.*?)\n\);", re.IGNORECASE | re.DOTALL | re.MULTILINE
)


@lru_cache(maxsize=8)
def _table_ddl(schema_name: str) -> dict[str, str]:
    """Each table's CREATE TABLE statement, taken from the hand-written DDL file."""
    text = (DDL_ROOT / f"{schema_name}.sql").read_text(encoding="utf-8")
    # Drop whole-line comments so the context is schema, not prose.
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))
    return {
        match.group(1).lower(): f"CREATE TABLE {match.group(1)} (\n{match.group(2)}\n);"
        for match in _CREATE_TABLE.finditer(body)
    }


def referenced_tables(sql: str, schema_name: str) -> list[str]:
    """Which of this schema's tables the statement mentions, in schema order.

    Parsed from the AST where possible. Oracle constructs sqlglot cannot parse
    fall back to a word search, which over-includes rather than under-includes:
    missing a table would leave the model guessing at column names.
    """
    known = list(SCHEMAS[schema_name].table_names)
    found: set[str] = set()

    try:
        parsed = sqlglot.parse_one(sql, read="oracle")
    except (ParseError, TokenError, RecursionError):
        parsed = None

    if parsed is not None:
        for table in parsed.find_all(exp.Table):
            name = (table.name or "").lower()
            if name in known:
                found.add(name)

    if not found:
        lowered = sql.lower()
        found = {name for name in known if re.search(rf"\b{name}\b", lowered)}

    return [name for name in known if name in found]


def build_system_prompt(sql: str, schema_name: str) -> str:
    """Task instructions plus the DDL for the tables this statement uses."""
    tables = referenced_tables(sql, schema_name)
    ddl = _table_ddl(schema_name)
    blocks = [ddl[name] for name in tables if name in ddl]

    if not blocks:
        # DDL units create their own scratch objects and reference nothing.
        return SYSTEM_PREAMBLE

    context = "\n\n".join(blocks)
    return f"{SYSTEM_PREAMBLE}\n\nOracle table definitions:\n\n{context}"


def build_messages(oracle_sql: str, postgres_sql: str, schema_name: str) -> list[dict[str, str]]:
    """The three-turn chat example. The assistant turn is the translation alone."""
    return [
        {"role": "system", "content": build_system_prompt(oracle_sql, schema_name)},
        {"role": "user", "content": oracle_sql.strip()},
        {"role": "assistant", "content": postgres_sql.strip()},
    ]
