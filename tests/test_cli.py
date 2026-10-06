"""The command surface: every stage is registered and documents itself."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from orashift import __version__
from orashift.cli import app

runner = CliRunner()

# Only --help is invoked for these here: seed, generate and verify would hit real
# databases, and build-dataset is exercised through tests/test_dataset.py.
COMMANDS = [
    "eval",
    "check-connections",
    "seed",
    "generate",
    "verify",
    "build-dataset",
    "version",
    "translate",
]


def test_help_lists_the_whole_pipeline():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in COMMANDS:
        assert command in result.output


@pytest.mark.parametrize("command", COMMANDS)
def test_every_command_has_help(command: str):
    """--help must work without touching a database."""
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0


def test_seed_rejects_an_unknown_schema():
    result = runner.invoke(app, ["seed", "--schema", "retial"])
    assert result.exit_code != 0


def test_version_command():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_translate_rejects_no_input():
    result = runner.invoke(app, ["translate"])
    assert result.exit_code == 2


def test_translate_rejects_both_inputs(tmp_path):
    sql_file = tmp_path / "units.sql"
    sql_file.write_text("SELECT 1 FROM dual;")
    result = runner.invoke(app, ["translate", "SELECT 1 FROM dual", "--file", str(sql_file)])
    assert result.exit_code == 2


def test_translate_a_statement_with_the_rules():
    result = runner.invoke(app, ["translate", "SELECT NVL(commission_pct, 0) FROM hr_employees"])
    assert result.exit_code == 0
    assert "COALESCE(commission_pct, 0)" in result.stdout


def test_translate_a_file_of_statements(tmp_path):
    sql_file = tmp_path / "units.sql"
    sql_file.write_text(
        "-- two independent statements\n"
        "SELECT NVL(a, 0) FROM t;\n"
        "SELECT DECODE(s, 'A', 1, 0) FROM t;\n"
    )
    result = runner.invoke(app, ["translate", "--file", str(sql_file)])
    assert result.exit_code == 0
    assert result.stdout.count(";") == 2
    assert "COALESCE(a, 0)" in result.stdout
    assert "CASE WHEN s = 'A' THEN 1 ELSE 0 END" in result.stdout
