"""Chart image generation for exports (velocity, delivered work).

matplotlib is an OPTIONAL dependency (``uv sync --extra charts``), lazy-imported
the same way voice.py handles its backends: every function degrades to ``None``
(with a log line) when the package is missing or rendering fails, so exports
simply omit the chart instead of crashing. The PNGs are written into the mode's
export directory and referenced from the generated Markdown as ``![alt](path)``
lines — the publish layer (export_targets.py) uploads them to Notion/Confluence
and localizes them for file exports.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Brand accent (the TUI's rgb(70,100,180)) + a muted grey for secondary series.
_ACCENT = "#4664b4"
_MUTED = "#9aa3b2"
_TEXT = "#333333"


def charts_available() -> bool:
    """True when matplotlib is importable (the ``charts`` extra is installed)."""
    try:
        import matplotlib  # noqa: F401

        return True
    except ImportError:
        return False


def _plt():
    """Import pyplot with the headless Agg backend, or None when unavailable."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except ImportError:
        logger.info("matplotlib not installed — skipping chart (install with: uv sync --extra charts)")
        return None


def _style_axes(ax) -> None:
    """Shared clean-light styling: no chrome, subtle grid, muted text."""
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(_MUTED)
    ax.tick_params(colors=_TEXT, labelsize=9)
    ax.yaxis.grid(True, color="#e6e8ec", linewidth=0.8)
    ax.set_axisbelow(True)


def velocity_chart(rows: list[tuple[str, float, float]], path: Path, title: str = "Sprint velocity") -> Path | None:
    """Render planned-vs-done grouped bars per sprint to *path* (PNG).

    *rows* is ``[(sprint_name, planned_points, done_points), …]``. Returns the
    written path, or None when matplotlib is unavailable, rows are empty, or
    rendering fails (best-effort — never raises).
    """
    plt = _plt()
    if plt is None or not rows:
        return None
    try:
        names = [r[0] for r in rows]
        planned = [r[1] for r in rows]
        done = [r[2] for r in rows]
        x = range(len(rows))
        width = 0.38

        fig, ax = plt.subplots(figsize=(max(5.0, 1.1 * len(rows) + 2), 3.2), dpi=150)
        ax.bar([i - width / 2 for i in x], planned, width, label="Planned", color=_MUTED)
        ax.bar([i + width / 2 for i in x], done, width, label="Done", color=_ACCENT)
        ax.set_xticks(list(x))
        ax.set_xticklabels(names, rotation=20, ha="right")
        ax.set_ylabel("Story points", color=_TEXT, fontsize=9)
        ax.set_title(title, color=_TEXT, fontsize=11, pad=10)
        ax.legend(frameon=False, fontsize=9)
        _style_axes(ax)
        fig.tight_layout()
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, facecolor="white")
        plt.close(fig)
        logger.info("Velocity chart written: %s (%d sprints)", path, len(rows))
        return path
    except Exception as e:  # noqa: BLE001 — charts are best-effort decoration
        logger.warning("Velocity chart failed: %s", e)
        return None


def delivered_chart(counts: list[tuple[str, int]], path: Path, title: str = "Delivered work") -> Path | None:
    """Render a simple bar chart of ``[(label, count), …]`` to *path* (PNG).

    Returns the written path, or None when matplotlib is unavailable, counts
    are empty, or rendering fails (best-effort — never raises).
    """
    plt = _plt()
    if plt is None or not counts:
        return None
    try:
        labels = [c[0] for c in counts]
        values = [c[1] for c in counts]

        fig, ax = plt.subplots(figsize=(max(5.0, 0.9 * len(counts) + 2), 3.2), dpi=150)
        ax.bar(range(len(counts)), values, 0.55, color=_ACCENT)
        ax.set_xticks(range(len(counts)))
        ax.set_xticklabels(labels, rotation=20, ha="right")
        ax.set_ylabel("Items", color=_TEXT, fontsize=9)
        ax.set_title(title, color=_TEXT, fontsize=11, pad=10)
        for i, v in enumerate(values):
            ax.text(i, v, str(v), ha="center", va="bottom", fontsize=8, color=_TEXT)
        _style_axes(ax)
        fig.tight_layout()
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, facecolor="white")
        plt.close(fig)
        logger.info("Delivered chart written: %s (%d bars)", path, len(counts))
        return path
    except Exception as e:  # noqa: BLE001 — charts are best-effort decoration
        logger.warning("Delivered chart failed: %s", e)
        return None
