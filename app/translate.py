"""The demo's translation path. It lives in the package, shared with `orashift translate`."""

from orashift.translate import (
    ADAPTER,
    ORACLE_ONLY,
    Translation,
    needs_model,
    preload,
    translate,
    try_sqlglot,
)

__all__ = [
    "ADAPTER",
    "ORACLE_ONLY",
    "Translation",
    "needs_model",
    "preload",
    "translate",
    "try_sqlglot",
]
