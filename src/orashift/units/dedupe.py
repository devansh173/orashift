"""Normalise statements with sqlglot so duplicates can be spotted.

Two templates can easily render the same statement for different schemas, and
whitespace or casing differences would hide that. Parsing into sqlglot's AST
and regenerating in a canonical form means statements that differ only
cosmetically collapse onto the same key.

If sqlglot cannot parse a statement the text is used instead, with whitespace
collapsed. That is deliberate: sqlglot not understanding an Oracle-ism is a
reason to keep the unit, not to drop it. Those are exactly the hard cases this
project exists to translate.
"""

from __future__ import annotations

import hashlib
import re

import sqlglot
from sqlglot.errors import ParseError, TokenError

_WHITESPACE = re.compile(r"\s+")


def normalize(sql: str) -> tuple[str, bool]:
    """Return a canonical form of the statement and whether sqlglot parsed it."""
    try:
        parsed = sqlglot.parse_one(sql, read="oracle")
    except (ParseError, TokenError, RecursionError):
        return _WHITESPACE.sub(" ", sql.strip().lower()), False
    if parsed is None:
        return _WHITESPACE.sub(" ", sql.strip().lower()), False
    return parsed.sql(dialect="oracle", normalize=True, pretty=False), True


def unit_key(sql: str) -> str:
    """A stable identifier derived from the normalised statement."""
    canonical, _parsed = normalize(sql)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
