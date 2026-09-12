"""The context capability's entry points — the one module every surface calls.

Thin on purpose: the grammar lives in :mod:`.scope`, the resolver in
:mod:`.resolve`, the label rows in :mod:`.labels`. What this module adds is the
options payload a picker draws (sources with counts, the label vocabulary, the
sprint calendar in use) and the label reads and writes as plain functions, so
the HTTP routes, the MCP tools and the TUI page share one validation.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from yeaboi.context import labels as _labels
from yeaboi.context import resolve as _resolve
from yeaboi.context import scope as _scope
from yeaboi.context.labels import LabelStore, SessionLabels
from yeaboi.context.scope import (
    SOURCE_HINTS,
    SOURCE_LABELS,
    SOURCES,
    WINDOW_KINDS,
    WINDOW_LABELS,
    ContextScope,
)
from yeaboi.context.window import load_sprint_calendar

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextOptions:
    """What a picker needs before a run starts: the vocabulary and what is there to read."""

    sources: tuple[dict, ...]  # {key, label, hint, count}
    windows: tuple[dict, ...]  # {kind, label, needs_count, needs_range}
    projects: tuple[str, ...]
    tags: tuple[dict, ...]  # {tag, count}
    calendar: dict  # {source, length_weeks, anchor_date, current: {number, start, end}}
    default: dict | None  # the mode's remembered scope, or None
    defaults: dict = field(default_factory=dict)  # {"tags": [...]} — the run's fixed tags


def parse_context_spec(spec: str) -> ContextScope | None:
    """The CLI/MCP grammar; ``""``/``inherit`` → ``None``. Raises ``ValueError`` on a typo."""
    return _scope.parse_context_spec(spec)


def resolve_scope(
    context: ContextScope | Mapping | str | None,
    *,
    today: date | None = None,
    db_path: Path | None = None,
) -> _resolve.Selection:
    """Resolve a scope into the ids each source may read (a ``None`` scope reads nothing)."""
    return _resolve.resolve_scope(context, today=today, db_path=db_path)


def preview_scope(
    context: ContextScope | Mapping | str | None = None,
    *,
    mode: str = "",
    rows: bool = False,
    today: date | None = None,
    db_path: Path | None = None,
) -> _resolve.Preview:
    """Counts per source under a scope, for the "12 standups · 2 retros · 4 Aug – 11 Sep" line.

    ``mode`` names the run being scoped; it only colours the log line — the
    reads are the same for every mode.
    """
    logger.info("context preview: mode=%s", mode or "-")
    return _resolve.preview_scope(context, today=today, db_path=db_path, rows=rows)


def context_options(mode: str = "", *, today: date | None = None, db_path: Path | None = None) -> ContextOptions:
    """Everything a picker draws before a run: sources with counts, labels, windows, the calendar."""
    from yeaboi.config import get_last_context_scope
    from yeaboi.paths import get_db_path

    if mode and mode not in _labels.LABEL_MODES:
        raise ValueError(f"unknown mode {mode!r} — one of {', '.join(_labels.LABEL_MODES)}")
    on = today or date.today()
    path = Path(db_path or get_db_path())
    counts = _resolve.preview_scope(ContextScope(), today=on, db_path=path).counts
    sources = tuple(
        {"key": key, "label": SOURCE_LABELS[key], "hint": SOURCE_HINTS.get(key, ""), "count": counts.get(key, 0)}
        for key in SOURCES
    )
    windows = tuple(
        {
            "kind": kind,
            "label": WINDOW_LABELS[kind],
            "needs_count": kind == "sprints",
            "needs_range": kind == "custom",
        }
        for kind in WINDOW_KINDS
    )
    projects: tuple[str, ...] = ()
    tags: tuple[dict, ...] = ()
    if path.exists():
        with LabelStore(path) as store:
            projects = tuple(store.list_projects())
            tags = tuple({"tag": tag, "count": n} for tag, n in store.list_tags())
    calendar = load_sprint_calendar(today=on, db_path=path)
    start, end = calendar.sprint_bounds(on)
    default = get_last_context_scope(mode) if mode else None
    options = ContextOptions(
        sources=sources,
        windows=windows,
        projects=projects,
        tags=tags,
        calendar={
            "source": calendar.source,
            "length_weeks": calendar.length_weeks,
            "anchor_date": calendar.anchor.isoformat(),
            "current": {"number": calendar.sprint_number(on), "start": start.isoformat(), "end": end.isoformat()},
        },
        default=default,
        defaults={"tags": list(_labels.default_tags(mode or "planning", today=on))},
    )
    logger.info(
        "context options: mode=%s projects=%d tags=%d calendar=%s",
        mode or "-",
        len(projects),
        len(tags),
        calendar.source,
    )
    return options


def set_session_labels(
    mode: str,
    session_id: str,
    run_id: str = "",
    *,
    project_label: str = "",
    tags: Sequence[str] = (),
    merge_tags: bool = True,
    db_path: Path | None = None,
) -> SessionLabels:
    """Write a run's project label and tags. Raises ``ValueError`` on an unknown mode or a blank id."""
    from yeaboi.paths import get_db_path

    with LabelStore(db_path or get_db_path()) as store:
        return store.set_labels(
            mode, session_id, str(run_id or ""), project=project_label, tags=tags, merge_tags=merge_tags
        )


def get_session_labels(
    mode: str, session_id: str, run_id: str = "", *, db_path: Path | None = None
) -> SessionLabels | None:
    """One run's labels, or ``None`` when it carries none. Raises ``ValueError`` on an unknown mode."""
    from yeaboi.paths import get_db_path

    if mode not in _labels.LABEL_MODES:
        raise ValueError(f"unknown mode {mode!r} — one of {', '.join(_labels.LABEL_MODES)}")
    path = Path(db_path or get_db_path())
    if not path.exists():
        return None
    with LabelStore(path) as store:
        return store.get_labels(mode, session_id, str(run_id or ""))


def list_session_labels(
    *,
    mode: str = "",
    project_label: str = "",
    tags: Sequence[str] = (),
    limit: int = 100,
    db_path: Path | None = None,
) -> list[SessionLabels]:
    """Label rows newest first, narrowed by mode, project label and required tags."""
    from yeaboi.paths import get_db_path

    if mode and mode not in _labels.LABEL_MODES:
        raise ValueError(f"unknown mode {mode!r} — one of {', '.join(_labels.LABEL_MODES)}")
    path = Path(db_path or get_db_path())
    if not path.exists():
        return []
    with LabelStore(path) as store:
        return store.list_labels(mode=mode, project=project_label, tags=tags, limit=limit)


def label_run(
    mode: str,
    session_id: str,
    run_id: int | str = "",
    *,
    project_label: str = "",
    tags: Sequence[str] = (),
    scope: ContextScope | dict | None = None,
    defaults: dict | None = None,
    db_path: Path | None = None,
    today: date | None = None,
) -> SessionLabels | None:
    """The write side every engine calls at record time; never raises."""
    return _labels.label_run(
        mode,
        session_id,
        run_id,
        project_label=project_label,
        tags=tags,
        scope=scope,
        defaults=defaults,
        db_path=db_path,
        today=today,
    )
