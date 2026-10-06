"""Evaluation: aggregation, the hybrid rule, and report rendering.

The scoring itself is the baseline verifier, already tested. What is new here is
the arithmetic that turns per-unit verdicts into the numbers the README quotes,
so that is what these cover.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orashift.eval import charts, report

METRICS = Path("results/metrics.json")


def test_pct_formats_a_cell():
    assert report._pct({"verified": 3, "total": 4, "rate": 0.75}) == "3/4 (75%)"


def test_pct_handles_an_empty_cell():
    """ora2pg has no units in some splits; it must not divide by zero."""
    assert report._pct({"verified": 0, "total": 0, "rate": 0.0}) == "n/a"


def test_splits_cover_both_holdout_axes():
    assert set(report.SPLITS) == {
        "test_in_schema",
        "test_unseen_schema",
        "test_unseen_template",
        "test_unseen_both",
    }


def test_every_split_has_a_human_label():
    assert set(report.SPLIT_LABELS) == set(report.SPLITS)


def test_charts_exclude_ora2pg():
    """It is scored over DDL only, so it has a different denominator. Putting it
    in the same bar chart would mislead."""
    assert "ora2pg" not in charts.STRATEGIES
    assert set(charts.STRATEGIES) <= set(report.MODEL_LABELS)


def test_chart_themes_supply_enough_series_colours():
    for theme in (charts.LIGHT, charts.DARK):
        assert len(theme.series) >= len(charts.STRATEGIES), theme.name


def test_light_and_dark_use_different_surfaces():
    """Dark mode is a selected palette, not an inverted one."""
    assert charts.LIGHT.surface != charts.DARK.surface
    assert charts.LIGHT.series != charts.DARK.series


# --------------------------------------------------------------------------- #
# The generated artefacts
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def metrics() -> dict:
    if not METRICS.exists():
        pytest.skip("metrics.json not built; run `orashift eval`")
    return json.loads(METRICS.read_text(encoding="utf-8"))


def test_metrics_cover_every_strategy(metrics):
    for model in ("base", "finetuned", "sqlglot", "hybrid"):
        assert model in metrics["execution_accuracy"], model


def test_rates_are_consistent_with_their_counts(metrics):
    """A rate that disagrees with its own numerator is how a README starts lying."""
    for section in ("execution_accuracy", "runs_without_error"):
        for model, cell in metrics[section].items():
            if cell["total"]:
                assert cell["rate"] == pytest.approx(cell["verified"] / cell["total"], abs=1e-4), (
                    f"{section}/{model}"
                )


def test_split_counts_sum_to_the_overall_count(metrics):
    for model, overall in metrics["execution_accuracy"].items():
        total = sum(metrics["by_split"][s][model]["total"] for s in report.SPLITS)
        assert total == overall["total"], model


def test_every_model_is_scored_on_the_same_units_except_ora2pg(metrics):
    """A comparison across different populations is not a comparison."""
    denominators = {
        model: cell["total"]
        for model, cell in metrics["execution_accuracy"].items()
        if model != "ora2pg"
    }
    assert len(set(denominators.values())) == 1, denominators


def test_hybrid_is_never_worse_than_its_own_fallback(metrics):
    """Hybrid takes sqlglot when it verifies, else the fine-tuned model, so it
    cannot score below the fine-tuned model."""
    hybrid = metrics["execution_accuracy"]["hybrid"]["verified"]
    finetuned = metrics["execution_accuracy"]["finetuned"]["verified"]
    assert hybrid >= finetuned


def test_verified_never_exceeds_total(metrics):
    for section in ("execution_accuracy", "runs_without_error"):
        for model, cell in metrics[section].items():
            assert cell["verified"] <= cell["total"], f"{section}/{model}"


def test_accuracy_never_exceeds_the_runs_without_error_rate(metrics):
    """A translation cannot be correct without having run."""
    for model in metrics["execution_accuracy"]:
        assert (
            metrics["execution_accuracy"][model]["verified"]
            <= metrics["runs_without_error"][model]["verified"]
        ), model


def test_failure_analysis_has_real_examples(metrics):
    for model in ("base", "finetuned"):
        analysis = metrics["failure_analysis"][model]
        assert analysis["failures"] > 0
        assert analysis["examples"]
        assert analysis["examples"][0]["oracle"]


def test_report_states_the_generalisation_limit():
    path = Path("results/report.md")
    if not path.exists():
        pytest.skip("report.md not built")
    text = path.read_text(encoding="utf-8")
    assert "did not generalise to new transformations" in text
    assert "Execution accuracy" in text
