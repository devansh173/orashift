"""The ``orashift`` command line interface.

The full command surface is registered from the start so the shape of the
pipeline is visible from ``orashift --help``. Commands belonging to later
phases exit with a clear message rather than pretending to work.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from orashift import __version__, catalog, db
from orashift.config import Settings, get_settings
from orashift.dataset import build as dataset_build
from orashift.dataset import card as dataset_card
from orashift.db.base import ServerInfo
from orashift.eval import charts as eval_charts
from orashift.eval import report as eval_report
from orashift.eval import score as eval_score
from orashift.logging import configure_logging, get_logger
from orashift.seed import generate as seed_generate
from orashift.seed import load as seed_load
from orashift.seed import verify as seed_verify
from orashift.units import generate as units_generate
from orashift.units import store as units_store
from orashift.verify import run as verify_run
from orashift.verify.candidates import CandidateSource

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


class SeedTarget(StrEnum):
    """Which engine(s) a seed run should touch."""

    ORACLE = "oracle"
    POSTGRES = "postgres"
    BOTH = "both"


def _resolve_schemas(names: list[str] | None) -> list[catalog.Schema]:
    if not names:
        return list(catalog.SCHEMAS.values())
    return [catalog.get_schema(name) for name in names]


def _print_seed_summary(title: str, loaded: dict[str, dict[str, int]]) -> None:
    table = Table(title=title, title_justify="left")
    table.add_column("Schema", style="bold")
    table.add_column("Table")
    table.add_column("Rows", justify="right")
    for schema_name, tables in loaded.items():
        for index, (table_name, rows) in enumerate(tables.items()):
            table.add_row(schema_name if index == 0 else "", table_name, str(rows))
    console.print(table)


def _print_verification(results: dict[str, list[seed_verify.TableComparison]]) -> bool:
    table = Table(title="Oracle vs PostgreSQL seed data", title_justify="left")
    table.add_column("Schema", style="bold")
    table.add_column("Table")
    table.add_column("Oracle", justify="right")
    table.add_column("Postgres", justify="right")
    table.add_column("Digest")
    table.add_column("Match")

    all_ok = True
    for schema_name, comparisons in results.items():
        for index, comparison in enumerate(comparisons):
            all_ok = all_ok and comparison.ok
            table.add_row(
                schema_name if index == 0 else "",
                comparison.table,
                str(comparison.oracle_rows),
                str(comparison.postgres_rows),
                comparison.oracle_digest[:12],
                "[green]yes[/]" if comparison.ok else "[red]NO[/]",
            )
    console.print(table)
    return all_ok


@app.command()
def seed(
    schema: Annotated[
        list[str] | None,
        typer.Option("--schema", "-s", help="Schema to load; repeatable. Default: all."),
    ] = None,
    target: Annotated[
        SeedTarget,
        typer.Option("--target", "-t", help="Which engine(s) to load."),
    ] = SeedTarget.BOTH,
    drop: Annotated[
        bool,
        typer.Option(
            "--drop/--no-drop", help="Drop existing objects first, making the run idempotent."
        ),
    ] = True,
    regenerate: Annotated[
        bool,
        typer.Option(
            "--regenerate", help="Rewrite the seed CSVs from the fixed seed before loading."
        ),
    ] = False,
    check: Annotated[
        bool,
        typer.Option("--verify/--no-verify", help="After loading both engines, compare the data."),
    ] = True,
) -> None:
    """Load the synthetic schemas and seed data into Oracle and PostgreSQL."""
    settings = get_settings()
    schemas = _resolve_schemas(schema)

    if regenerate:
        counts = seed_generate.generate_all()
        total = sum(rows for tables in counts.values() for rows in tables.values())
        console.print(
            f"Regenerated {total} rows of seed data into {seed_generate.DEFAULT_OUT_DIR}/"
        )

    dialects = {
        SeedTarget.ORACLE: [seed_load.ORACLE],
        SeedTarget.POSTGRES: [seed_load.POSTGRES],
        SeedTarget.BOTH: [seed_load.ORACLE, seed_load.POSTGRES],
    }[target]

    for dialect in dialects:
        loaded: dict[str, dict[str, int]] = {}
        for schema_def in schemas:
            try:
                loaded[schema_def.name] = seed_load.seed_schema(
                    settings, schema_def, dialect, drop=drop
                )
            except Exception as exc:
                err_console.print(
                    f"[red]{dialect.name}: failed loading schema {schema_def.name}:[/] {exc}"
                )
                raise typer.Exit(code=1) from exc
        _print_seed_summary(f"Loaded into {dialect.name}", loaded)

    if not check:
        return
    if target is not SeedTarget.BOTH:
        console.print("[yellow]Skipping comparison: it needs both engines loaded.[/]")
        return

    results = {s.name: seed_verify.compare_schema(settings, s) for s in schemas}
    if _print_verification(results):
        console.print("[green]Both engines hold identical seed data.[/]")
    else:
        err_console.print("[red]Seed data differs between the engines.[/]")
        raise typer.Exit(code=1)


@app.command()
def generate(
    verify_on_oracle: Annotated[
        bool,
        typer.Option(
            "--verify/--no-verify",
            help="Run every new unit against Oracle and drop the ones that fail.",
        ),
    ] = True,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit", help="Only verify this many pending units; useful for a smoke run."
        ),
    ] = None,
    show_failures: Annotated[
        bool,
        typer.Option("--show-failures", help="List the most common failure reasons."),
    ] = False,
) -> None:
    """Generate the pool of Oracle source units (queries, DDL and DML)."""
    settings = get_settings()

    summary = units_generate.generate()
    console.print(
        f"Rendered {summary.rendered} statements, "
        f"{summary.inserted} new, "
        f"{summary.collapsed} collapsed as duplicates."
    )

    if verify_on_oracle:
        result = units_generate.verify_on_oracle(settings, limit=limit)
        console.print(
            f"Ran {result.checked} against Oracle: "
            f"[green]{result.verified} verified[/], [red]{result.failed} failed[/]."
        )

    _print_yield_report()

    if show_failures:
        failures = units_generate.failure_breakdown()
        if failures:
            table = Table(title="Most common failures", title_justify="left")
            table.add_column("Count", justify="right")
            table.add_column("Reason")
            table.add_column("Example template")
            for reason, count, template_id in failures:
                table.add_row(str(count), reason or "-", template_id or "-")
            console.print(table)


def _print_yield_report() -> None:
    """Per category: generated, kept, dropped. A weak category cannot hide here."""
    with units_store.connect() as conn:
        rows = units_store.yield_report(conn)

    table = Table(title="Unit pool yield", title_justify="left")
    table.add_column("Type", style="bold")
    table.add_column("Category")
    table.add_column("Total", justify="right")
    table.add_column("Verified", justify="right")
    table.add_column("Failed", justify="right")
    table.add_column("Yield", justify="right")

    totals = {"total": 0, "verified": 0, "failed": 0}
    last_type = None
    for row in rows:
        total = int(row["total"])
        verified = int(row["verified"] or 0)
        failed = int(row["failed"] or 0)
        totals["total"] += total
        totals["verified"] += verified
        totals["failed"] += failed
        rate = verified / total if total else 0.0
        colour = "green" if rate >= 0.8 else "yellow" if rate >= 0.4 else "red"
        table.add_row(
            str(row["unit_type"]) if row["unit_type"] != last_type else "",
            str(row["category"]),
            str(total),
            str(verified),
            str(failed),
            f"[{colour}]{rate:.0%}[/]",
        )
        last_type = row["unit_type"]

    overall = totals["verified"] / totals["total"] if totals["total"] else 0.0
    table.add_section()
    table.add_row(
        "",
        "[bold]all[/]",
        str(totals["total"]),
        str(totals["verified"]),
        str(totals["failed"]),
        f"[bold]{overall:.0%}[/]",
    )
    console.print(table)


@app.command()
def verify(
    source: Annotated[
        list[str] | None,
        typer.Option(
            "--source", "-s", help="Candidate source; repeatable. Default: gold, sqlglot."
        ),
    ] = None,
    limit: Annotated[
        int | None, typer.Option("--limit", help="Verify only this many units per source.")
    ] = None,
    resume: Annotated[
        bool,
        typer.Option("--resume/--rerun", help="Skip units already attempted for that source."),
    ] = True,
    show_failures: Annotated[
        bool, typer.Option("--show-failures", help="Break down why candidates failed.")
    ] = False,
) -> None:
    """Produce translation candidates and verify them by execution on both engines."""
    settings = get_settings()
    chosen = [CandidateSource(name) for name in (source or ["gold", "sqlglot"])]

    summaries = []
    for candidate in chosen:
        if candidate is CandidateSource.ORA2PG:
            try:
                summary = verify_run.run_ora2pg(settings, resume=resume)
            except Exception as exc:
                err_console.print(f"[yellow]ora2pg baseline skipped:[/] {exc}")
                continue
        else:
            summary = verify_run.run_source(settings, candidate, limit=limit, resume=resume)
        summaries.append(summary)
        console.print(
            f"{candidate}: {summary.verified}/{summary.attempted} verified "
            f"({summary.execution_accuracy:.0%}), "
            f"{summary.runs_without_error:.0%} ran without error"
        )

    _print_accuracy_table()

    if show_failures:
        for candidate in chosen:
            rows = verify_run.failure_reasons(candidate)
            if not rows:
                continue
            table = Table(title=f"Why {candidate} failed", title_justify="left")
            table.add_column("Count", justify="right")
            table.add_column("Reason")
            table.add_column("Example category")
            table.add_column("Example detail", max_width=60)
            for reason, count, category, detail in rows:
                table.add_row(str(count), reason or "-", category or "-", (detail or "-")[:200])
            console.print(table)


def _print_accuracy_table() -> None:
    """Execution accuracy per source and category, side by side."""
    with units_store.connect() as conn:
        rows = units_store.attempt_report(conn)
        totals = units_store.source_totals(conn)

    sources = sorted({str(r["source"]) for r in rows})
    by_key: dict[tuple[str, str, str], dict[str, object]] = {
        (str(r["source"]), str(r["unit_type"]), str(r["category"])): r for r in rows
    }
    categories = sorted({(str(r["unit_type"]), str(r["category"])) for r in rows})

    table = Table(title="Execution accuracy by category", title_justify="left")
    table.add_column("Type", style="bold")
    table.add_column("Category")
    for name in sources:
        table.add_column(name, justify="right")

    last_type = None
    for unit_type, category in categories:
        cells = []
        for name in sources:
            row = by_key.get((name, unit_type, category))
            if row is None:
                cells.append("-")
                continue
            attempted = int(row["attempted"])
            verified = int(row["verified"] or 0)
            rate = verified / attempted if attempted else 0.0
            colour = "green" if rate >= 0.9 else "yellow" if rate >= 0.5 else "red"
            cells.append(f"[{colour}]{verified}/{attempted}[/]")
        table.add_row(unit_type if unit_type != last_type else "", category, *cells)
        last_type = unit_type

    table.add_section()
    totals_by_source = {str(t["source"]): t for t in totals}
    overall = []
    for name in sources:
        t = totals_by_source.get(name)
        if t is None:
            overall.append("-")
            continue
        attempted, verified = int(t["attempted"]), int(t["verified"] or 0)
        rate = verified / attempted if attempted else 0.0
        overall.append(f"[bold]{verified}/{attempted} ({rate:.0%})[/]")
    table.add_row("", "[bold]all[/]", *overall)
    console.print(table)


@app.command("build-dataset")
def build_dataset(
    out_dir: Annotated[
        Path, typer.Option("--out", help="Where to write the JSONL splits.")
    ] = dataset_build.DEFAULT_OUT_DIR,
    max_tokens: Annotated[
        int, typer.Option("--max-tokens", help="Estimated token budget per example.")
    ] = dataset_build.MAX_SEQ_LENGTH,
) -> None:
    """Turn verified pairs into train/val/test chat JSONL splits."""
    report = dataset_build.build(out_dir, max_tokens=max_tokens)

    table = Table(title="Dataset splits", title_justify="left")
    table.add_column("Split", style="bold")
    table.add_column("Examples", justify="right")
    table.add_column("Share", justify="right")
    for name, count in report.counts.items():
        share = count / report.total if report.total else 0.0
        table.add_row(name, str(count), f"{share:.0%}")
    table.add_section()
    table.add_row("[bold]total[/]", f"[bold]{report.total}[/]", "")
    console.print(table)

    console.print(
        f"Longest example ~{report.longest} estimated tokens "
        f"(budget {max_tokens}); {report.excluded} excluded as too long."
    )
    console.print(
        "[yellow]Token counts are estimates.[/] The real tokenizer cannot run here "
        "(this network blocks huggingface.co); the training notebook re-measures."
    )

    if report.thin_categories:
        thin = Table(title="Categories too thin to train on", title_justify="left")
        thin.add_column("Category")
        thin.add_column("Training examples", justify="right")
        for category, count in report.thin_categories:
            thin.add_row(category, str(count))
        console.print(thin)

    card_path = dataset_card.write(report, out_dir / "README.md")
    console.print(f"Wrote splits and dataset card to {out_dir}/")
    console.print(f"  card: {card_path}")


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
def run_eval(
    rescore: Annotated[
        bool, typer.Option("--rescore", help="Re-execute predictions already scored.")
    ] = False,
    limit: Annotated[
        int | None, typer.Option("--limit", help="Score only this many per model.")
    ] = None,
    make_charts: Annotated[
        bool, typer.Option("--charts/--no-charts", help="Render the README charts.")
    ] = True,
) -> None:
    """Score every translation strategy by execution and write results/."""
    settings = get_settings()

    summaries = eval_score.score_all(settings, resume=not rescore, limit=limit)
    for summary in summaries.values():
        console.print(
            f"{summary.model}: {summary.verified}/{summary.scored} verified "
            f"({summary.execution_accuracy:.1%}), "
            f"{summary.runs_without_error:.1%} ran without error"
        )

    metrics_path, report_path = eval_report.write()
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    table = Table(title="Execution accuracy", title_justify="left")
    table.add_column("Strategy", style="bold")
    table.add_column("Overall", justify="right")
    for split in eval_report.SPLITS:
        table.add_column(split.replace("test_", ""), justify="right")

    for model in metrics["models"]:
        cells = []
        for split in eval_report.SPLITS:
            cell = metrics["by_split"][split][model]
            cells.append(f"{cell['rate']:.0%}" if cell["total"] else "-")
        overall = metrics["execution_accuracy"][model]
        table.add_row(
            model, f"{overall['rate']:.0%} ({overall['verified']}/{overall['total']})", *cells
        )
    console.print(table)

    console.print(f"\nwrote {metrics_path} and {report_path}")

    if make_charts:
        for path in eval_charts.write_all():
            console.print(f"  chart: {path}")
