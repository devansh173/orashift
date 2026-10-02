"""Produce candidate PostgreSQL translations for a unit, by source."""

from __future__ import annotations

import logging
from enum import StrEnum

import sqlglot
from sqlglot.errors import ParseError, TokenError, UnsupportedError

from orashift.units.anchors import ANCHORS
from orashift.units.translations import TRANSLATIONS
from orashift.units.types import Unit


class CandidateSource(StrEnum):
    """Where a candidate translation came from.

    `GOLD` is the hand-written reference. The others are baselines, measured
    with exactly the same verifier so the comparison is fair.
    """

    GOLD = "gold"
    SQLGLOT = "sqlglot"
    ORA2PG = "ora2pg"
    LLM = "llm"


def render_gold(unit: Unit) -> str | None:
    """The hand-written translation for this unit's template, rendered for its schema."""
    if unit.template_id is None:
        return None
    translation = TRANSLATIONS.get(unit.template_id)
    if translation is None:
        return None

    anchors = ANCHORS.get(unit.schema_name)
    if anchors is None:
        return None

    params: dict[str, str] = {}
    for key, value in unit.metadata.items():
        if not key.startswith("param_"):
            continue
        name = key.removeprefix("param_")
        mapping = translation.param_translate.get(name)
        params[name] = mapping.get(value, value) if mapping else value

    objects = {key: value for key, value in unit.metadata.items() if key.startswith("object_")}
    objects = {f"obj{k.removeprefix('object_')}": v for k, v in objects.items()}

    try:
        return translation.sql.format(**anchors.as_dict(), **objects, **params)
    except KeyError:
        return None


# sqlglot logs a warning for every construct it cannot convert. Those are the
# interesting cases, but they are counted from the verification results rather
# than read off the console, so the log is quietened here.
logging.getLogger("sqlglot").setLevel(logging.ERROR)


def render_sqlglot(unit: Unit) -> str | None:
    """What the rule-based transpiler produces.

    Returns None only when sqlglot raises. Note that it often returns the input
    almost unchanged for constructs it does not understand -- CONNECT BY comes
    back as CONNECT BY -- which then fails on PostgreSQL. That is a real
    baseline result and is counted as such, not treated as an error here.
    """
    try:
        converted = sqlglot.transpile(unit.sql_text, read="oracle", write="postgres", pretty=False)
    except (ParseError, TokenError, UnsupportedError, RecursionError, KeyError, ValueError):
        return None
    if not converted:
        return None
    return "; ".join(part.strip() for part in converted if part.strip())


RENDERERS = {
    CandidateSource.GOLD: render_gold,
    CandidateSource.SQLGLOT: render_sqlglot,
}
