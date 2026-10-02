"""Compare two result sets, one from each engine.

This is where "correct" is actually defined, so the rules are deliberate:

* **Ordering.** Compared as a sequence only when the statement has a top-level
  ``ORDER BY``. Without one, both engines are free to return rows in any order,
  so comparing as a sequence would fail correct translations. Everything else is
  compared as a multiset — duplicates still matter, position does not.
* **Numbers.** Compared as decimal values rounded to a fixed number of places,
  never as text. Phase 1 measured why: a non-terminating division keeps 38
  significant digits in Oracle's NUMBER and about 16 in PostgreSQL's numeric, so
  ``15.2083333333333333`` and ``15.20833333333333333333333333333333333333`` are
  the same number and must compare equal.
* **Shape only.** Some statements cannot be value-compared at all — an
  unordered ``ROWNUM <= 3`` legitimately selects a different three rows on each
  engine, and two sequences advance independently. Those are compared on row
  and column count, which still catches a translation that fails to run or
  returns the wrong shape.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import sqlglot
from sqlglot.errors import ParseError, TokenError

DECIMAL_PLACES = 6
"""Numbers are compared to this many decimal places. Chosen because it is far
finer than any value in the seed data and far coarser than the precision
difference between the two engines' division."""

NULL_MARKER = "\x00NULL"

_ORDER_BY = re.compile(r"\border\s+(?:siblings\s+)?by\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ResultSet:
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.rows), len(self.columns)


@dataclass(frozen=True, slots=True)
class Comparison:
    ok: bool
    reason: str | None = None
    oracle_shape: tuple[int, int] | None = None
    postgres_shape: tuple[int, int] | None = None
    first_difference: str | None = None


def has_top_level_order_by(sql: str) -> bool:
    """Whether the outermost query orders its rows.

    An ORDER BY inside a subquery does not make the final result ordered, so the
    AST is consulted rather than the text. If sqlglot cannot parse the statement
    the text is checked instead, erring towards treating it as ordered only when
    an ORDER BY appears outside any parentheses.
    """
    try:
        parsed = sqlglot.parse_one(sql, read="oracle")
    except (ParseError, TokenError, RecursionError):
        parsed = None

    if parsed is not None:
        return parsed.args.get("order") is not None

    depth = 0
    for match in re.finditer(r"[()]|\border\s+(?:siblings\s+)?by\b", sql, re.IGNORECASE):
        token = match.group(0)
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
        elif depth == 0:
            return True
    return False


def canonical(value: Any, places: int = DECIMAL_PLACES) -> str:
    """One value as engine-independent text, with numbers rounded."""
    if value is None:
        return NULL_MARKER
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, Decimal | float | int) and not isinstance(value, bool):
        return _canonical_number(value, places)
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, dt.date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, dt.timedelta):
        return _canonical_number(Decimal(value.total_seconds()), places)
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).hex()
    if isinstance(value, list | tuple):
        return "[" + ",".join(canonical(v, places) for v in value) + "]"
    return str(value)


def _canonical_number(value: Decimal | float | int, places: int) -> str:
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(repr(value))
    except (InvalidOperation, ValueError):
        return str(value)
    try:
        rounded = round(decimal_value, places)
    except (InvalidOperation, ValueError, OverflowError):
        rounded = decimal_value
    normalised = rounded.normalize()
    # normalize() turns 500 into 5E+2; 'f' puts it back.
    return format(normalised, "f")


def _canonical_rows(result: ResultSet, places: int) -> list[tuple[str, ...]]:
    return [tuple(canonical(value, places) for value in row) for row in result.rows]


def compare_results(
    oracle: ResultSet,
    postgres: ResultSet,
    *,
    ordered: bool,
    compare_values: bool = True,
    places: int = DECIMAL_PLACES,
) -> Comparison:
    """Decide whether two result sets count as the same."""
    shapes = {"oracle_shape": oracle.shape, "postgres_shape": postgres.shape}

    if len(oracle.columns) != len(postgres.columns):
        return Comparison(
            False,
            f"column count differs: {len(oracle.columns)} vs {len(postgres.columns)}",
            **shapes,
        )
    if len(oracle.rows) != len(postgres.rows):
        return Comparison(
            False,
            f"row count differs: {len(oracle.rows)} vs {len(postgres.rows)}",
            **shapes,
        )
    if not compare_values:
        return Comparison(True, **shapes)

    left = _canonical_rows(oracle, places)
    right = _canonical_rows(postgres, places)

    if not ordered:
        left = sorted(left)
        right = sorted(right)

    for index, (a, b) in enumerate(zip(left, right, strict=True)):
        if a != b:
            return Comparison(
                False,
                "row values differ",
                first_difference=(
                    f"row {index}: oracle={a!r} postgres={b!r}"
                    if ordered
                    else f"sorted row {index}: oracle={a!r} postgres={b!r}"
                ),
                **shapes,
            )
    return Comparison(True, **shapes)
