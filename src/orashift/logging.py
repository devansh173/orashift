"""Structured logging setup.

Logs go to stderr so that stdout stays clean for machine-readable CLI output.
``console`` format is for humans at a terminal; ``json`` emits one JSON object
per line, which is what you want when a run is piped to a file and inspected
later.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from orashift.config import LogFormat

_configured = False


def _stderr_logger_factory(*_args: Any) -> structlog.PrintLogger:
    """A fresh logger bound to whatever sys.stderr is right now."""
    return structlog.PrintLogger(sys.stderr)


def configure_logging(level: str = "INFO", fmt: LogFormat = "console") -> None:
    """Configure structlog. Safe to call more than once; later calls reconfigure."""
    global _configured

    numeric_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        # Resolve sys.stderr at write time, not at configure time. Binding the
        # stream here would leave cached loggers holding a stale handle if
        # anything swaps stdio out and back, which test runners and CLI
        # harnesses both do.
        logger_factory=_stderr_logger_factory,
        cache_logger_on_first_use=False,
    )
    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound logger, configuring logging with defaults if needed."""
    if not _configured:
        configure_logging()
    return structlog.get_logger(name)
