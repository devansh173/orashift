"""Charts for the README, drawn from results/metrics.json.

Colour choices follow a validated categorical palette: the four hues used here
were checked for colourblind separation, chroma and lightness band before being
committed to, rather than picked by eye. The validator reported a sub-3:1
contrast warning against the chart surface, which obliges visible labels, so
every bar carries its own value.

Both a light and a dark version of each chart are written, and the README
selects between them with `<picture>`. A light-surface PNG on a dark page is
unreadable, and inverting one automatically produces muddy hues.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

RESULTS_DIR = Path("results")
METRICS_PATH = RESULTS_DIR / "metrics.json"

# Strategies sharing the same 330-unit denominator. ora2pg is deliberately left
# out of the charts: it only translates DDL, so it is scored over 11 units, and
# putting a different denominator in the same bar chart would mislead.
STRATEGIES = ("base", "finetuned", "sqlglot", "hybrid")

SHORT_LABELS = {
    "base": "Base model",
    "finetuned": "Fine-tuned",
    "sqlglot": "sqlglot",
    "hybrid": "Hybrid",
}

SPLIT_SHORT = {
    "test_in_schema": "Seen schema\nseen template",
    "test_unseen_schema": "Unseen schema\nseen template",
    "test_unseen_template": "Seen schema\nunseen template",
    "test_unseen_both": "Unseen schema\nunseen template",
}


@dataclass(frozen=True, slots=True)
class Theme:
    name: str
    surface: str
    text_primary: str
    text_secondary: str
    grid: str
    axis: str
    series: tuple[str, ...]


LIGHT = Theme(
    name="light",
    surface="#fcfcfb",
    text_primary="#0b0b0b",
    text_secondary="#52514e",
    grid="#e1e0d9",
    axis="#c3c2b7",
    series=("#2a78d6", "#eb6834", "#1baf7a", "#eda100"),
)

DARK = Theme(
    name="dark",
    surface="#1a1a19",
    text_primary="#ffffff",
    text_secondary="#c3c2b7",
    grid="#2c2c2a",
    axis="#383835",
    series=("#3987e5", "#d95926", "#199e70", "#c98500"),
)


def _style(ax: Any, theme: Theme) -> None:
    """Recessive grid and axes; no chartjunk."""
    ax.set_facecolor(theme.surface)
    ax.grid(axis="x", color=theme.grid, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(theme.axis)
    ax.spines["bottom"].set_linewidth(1.0)
    ax.tick_params(colors=theme.text_secondary, length=0, labelsize=10)


def headline(metrics: dict[str, Any], theme: Theme, path: Path) -> Path:
    """One bar per strategy. A single series, so no legend: the title names it."""
    rates = [metrics["execution_accuracy"][s]["rate"] for s in STRATEGIES]
    counts = [metrics["execution_accuracy"][s] for s in STRATEGIES]
    order = sorted(range(len(STRATEGIES)), key=lambda i: rates[i])

    fig, ax = plt.subplots(figsize=(8.2, 3.4), facecolor=theme.surface)
    positions = range(len(order))
    ax.barh(
        list(positions),
        [rates[i] for i in order],
        height=0.56,
        color=[theme.series[i] for i in order],
        zorder=2,
    )
    ax.set_yticks(list(positions))
    ax.set_yticklabels(
        [SHORT_LABELS[STRATEGIES[i]] for i in order], color=theme.text_primary, fontsize=11
    )
    ax.set_xlim(0, 1.0)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
    _style(ax, theme)

    # Direct labels: required relief for the sub-3:1 contrast warning.
    for position, index in zip(positions, order, strict=True):
        cell = counts[index]
        ax.text(
            rates[index] + 0.012,
            position,
            f"{cell['rate']:.0%}  ({cell['verified']}/{cell['total']})",
            va="center",
            ha="left",
            color=theme.text_primary,
            fontsize=10,
        )

    ax.set_title(
        "Execution accuracy on 330 held-out test units",
        color=theme.text_primary,
        fontsize=13,
        pad=14,
        loc="left",
    )
    ax.text(
        0,
        -0.30,
        "Ran on PostgreSQL and returned what Oracle returned",
        transform=ax.transAxes,
        color=theme.text_secondary,
        fontsize=9.5,
    )

    fig.tight_layout()
    fig.savefig(path, dpi=200, facecolor=theme.surface, bbox_inches="tight")
    plt.close(fig)
    return path


def by_split(metrics: dict[str, Any], theme: Theme, path: Path) -> Path:
    """Grouped bars: the generalisation story, which is the real finding."""
    splits = list(SPLIT_SHORT)
    group_width = 0.78
    bar_width = group_width / len(STRATEGIES)

    fig, ax = plt.subplots(figsize=(10.5, 4.3), facecolor=theme.surface)
    for index, strategy in enumerate(STRATEGIES):
        rates = [metrics["by_split"][s][strategy]["rate"] for s in splits]
        # A 2px surface gap between adjacent bars, per the mark spec.
        offsets = [
            i + index * bar_width - group_width / 2 + bar_width / 2 for i in range(len(splits))
        ]
        bars = ax.bar(
            offsets,
            rates,
            width=bar_width * 0.88,
            color=theme.series[index],
            label=SHORT_LABELS[strategy],
            zorder=2,
        )
        for bar, rate in zip(bars, rates, strict=True):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                rate + 0.02,
                f"{rate:.0%}",
                ha="center",
                va="bottom",
                color=theme.text_secondary,
                fontsize=8.5,
            )

    ax.set_xticks(range(len(splits)))
    ax.set_xticklabels([SPLIT_SHORT[s] for s in splits], color=theme.text_primary, fontsize=10)
    ax.set_ylim(0, 1.12)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.set_facecolor(theme.surface)
    ax.grid(axis="y", color=theme.grid, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(theme.axis)
    ax.tick_params(colors=theme.text_secondary, length=0, labelsize=10)

    legend = ax.legend(
        loc="upper right", frameon=False, ncol=4, fontsize=10, bbox_to_anchor=(1.0, 1.16)
    )
    for text in legend.get_texts():
        text.set_color(theme.text_primary)

    ax.set_title(
        "Where the fine-tune helps, and where it does not",
        color=theme.text_primary,
        fontsize=13,
        pad=30,
        loc="left",
    )
    ax.text(
        0,
        -0.26,
        "The gain is confined to splits whose template was seen in training",
        transform=ax.transAxes,
        color=theme.text_secondary,
        fontsize=9.5,
    )

    fig.tight_layout()
    fig.savefig(path, dpi=200, facecolor=theme.surface, bbox_inches="tight")
    plt.close(fig)
    return path


def write_all(metrics_path: Path = METRICS_PATH) -> list[Path]:
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for theme in (LIGHT, DARK):
        suffix = "" if theme.name == "light" else "-dark"
        written.append(headline(metrics, theme, RESULTS_DIR / f"accuracy{suffix}.png"))
        written.append(by_split(metrics, theme, RESULTS_DIR / f"generalisation{suffix}.png"))
    return written
