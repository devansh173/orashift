"""The command surface: what exists, and how unfinished commands behave."""

from __future__ import annotations

import pytest
import typer
from typer.testing import CliRunner

from orashift import __version__
from orashift.cli import _not_implemented, app

runner = CliRunner()

# Commands still stubbed out. `seed` (phase 1), `generate` (phase 2) and
# `verify` (phase 3) are covered by the db-marked tests, so they must not be
# invoked here: that would hit real databases.
LATER_PHASE_COMMANDS = ["build-dataset", "eval"]
IMPLEMENTED_COMMANDS = ["check-connections", "seed", "generate", "verify", "version"]


def test_help_lists_the_whole_pipeline():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in [*IMPLEMENTED_COMMANDS, *LATER_PHASE_COMMANDS, "translate"]:
        assert command in result.output


@pytest.mark.parametrize("command", IMPLEMENTED_COMMANDS)
def test_implemented_commands_have_help(command: str):
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


@pytest.mark.parametrize("command", LATER_PHASE_COMMANDS)
def test_later_phase_commands_fail_instead_of_pretending(command: str):
    result = runner.invoke(app, [command])
    assert result.exit_code == 1


def test_not_implemented_names_the_phase(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(typer.Exit) as excinfo:
        _not_implemented(4, "build-dataset")
    assert excinfo.value.exit_code == 1
    message = capsys.readouterr().err
    assert "build-dataset" in message
    assert "phase 4" in message


def test_translate_rejects_no_input():
    result = runner.invoke(app, ["translate"])
    assert result.exit_code == 2


def test_translate_rejects_both_inputs(tmp_path):
    sql_file = tmp_path / "units.sql"
    sql_file.write_text("SELECT 1 FROM dual;")
    result = runner.invoke(app, ["translate", "SELECT 1 FROM dual", "--file", str(sql_file)])
    assert result.exit_code == 2
