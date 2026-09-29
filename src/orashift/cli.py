"""The ``orashift`` command line interface.

The full command surface is registered from the start so the shape of the
pipeline is visible from ``orashift --help``. Commands belonging to later
phases exit with a clear message rather than pretending to work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from orashift import __version__, db
from orashift.config import Settings, get_settings
from orashift.db.base import ServerInfo
from orashift.logging import configure_logging, get_logger

app = typer.Typer(
    name="orashift",
    help="Translate Oracle SQL to PostgreSQL and verify the translation by executing it.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
err_console = Console(stderr=True)
log = get_logger(__name__)


def _not_implemented(phase: int, what: str) -> NoReturn:
    """Fail loudly for commands whose phase has not landed yet."""
    err_console.print(f"[yellow]{what} is not implemented yet (arrives in phase {phase}).[/]")
    raise typer.Exit(code=1)


@app.callback()
def main(
    log_level: Annotated[
        str | None,
        typer.Option("--log-level", help="Override LOG_LEVEL, e.g. DEBUG."),
    ] = None,
    log_format: Annotated[
        str | None,
        typer.Option("--log-format", help="Override LOG_FORMAT: console or json."),
    ] = None,
) -> None:
    """Configure logging before any subcommand runs."""
    settings = get_settings()
    configure_logging(
        level=log_level or settings.log_level,
        fmt=log_format or settings.log_format,  # type: ignore[arg-type]
    )


@app.command()
def version() -> None:
    """Print the OraShift version."""
    console.print(__version__)


def _probe_all(settings: Settings) -> list[tuple[str, str, ServerInfo | Exception]]:
    """Probe both databases, capturing failures instead of raising."""
    targets = (
        ("Oracle", settings.oracle_dsn, db.oracle.probe),
        ("PostgreSQL", settings.pg_target, db.postgres.probe),
    )
    results: list[tuple[str, str, ServerInfo | Exception]] = []
    for label, target, probe in targets:
        try:
            info = probe(settings)
        # Broad by design: one database being down must not hide the other's status.
        except Exception as exc:
            log.error("connection_failed", database=label, target=target, error=str(exc))
            results.append((label, target, exc))
        else:
            log.info("connection_ok", database=label, target=target, version=info.version)
            results.append((label, target, info))
    return results


@app.command("check-connections")
def check_connections() -> None:
    """Connect to Oracle and PostgreSQL and print the server versions."""
    settings = get_settings()
    results = _probe_all(settings)

    table = Table(title="OraShift connection check", title_justify="left")
    table.add_column("Database", style="bold")
    table.add_column("Target")
    table.add_column("Status")
    table.add_column("Version")
    table.add_column("Connected as")

    for label, target, outcome in results:
        if isinstance(outcome, Exception):
            table.add_row(label, target, "[red]FAIL[/]", "-", f"[red]{outcome}[/]")
        else:
            table.add_row(label, target, "[green]OK[/]", outcome.version, f"{outcome.username}")

    console.print(table)

    for label, _target, outcome in results:
        if isinstance(outcome, ServerInfo):
            console.print(f"  {label}: {outcome.banner}")

    if any(isinstance(outcome, Exception) for _, _, outcome in results):
        err_console.print(
            "\n[red]At least one connection failed.[/] "
            "Check your .env and that both databases are running."
        )
        raise typer.Exit(code=1)


@app.command()
def seed() -> None:
    """Load the synthetic schemas and seed data into Oracle and PostgreSQL."""
    _not_implemented(1, "seed")


@app.command()
def generate() -> None:
    """Generate the pool of Oracle source units (queries and DDL)."""
    _not_implemented(2, "generate")


@app.command()
def verify() -> None:
    """Produce translation candidates and verify them by execution."""
    _not_implemented(3, "verify")


@app.command("build-dataset")
def build_dataset() -> None:
    """Turn verified pairs into train/val/test chat JSONL splits."""
    _not_implemented(4, "build-dataset")


@app.command()
def translate(
    sql: Annotated[
        str | None,
        typer.Argument(help="A single Oracle statement to translate."),
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="A .sql file of independent Oracle statements."),
    ] = None,
) -> None:
    """Translate Oracle SQL to PostgreSQL."""
    if (sql is None) == (file is None):
        err_console.print("[red]Provide exactly one of: a SQL argument, or --file.[/]")
        raise typer.Exit(code=2)
    _not_implemented(3, "translate")


@app.command("eval")
def run_eval() -> None:
    """Score every translation strategy and write results/metrics.json."""
    _not_implemented(7, "eval")
