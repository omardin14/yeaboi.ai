"""Resolving a scope into the run ids each store may read.

``resolve_scope`` turns a :class:`ContextScope` into a :class:`Selection`:
per source, the ids that fall inside the window, carry the labels, and
survive the per-source cap — or ``None`` when that source is unrestricted.
A ``None`` scope resolves without a single store read, which is what keeps
``context=None`` byte-for-byte today's behaviour. A store that fails degrades
to unrestricted with a warning; resolution never raises.

``preview_scope`` is the same walk with counts, for the surfaces' "12
standups · 2 retros · 4 Aug – 11 Sep" line.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from yeaboi.context.labels import LabelStore, normalize_tags
from yeaboi.context.scope import SOURCE_LABELS, SOURCES, ContextScope, coerce_scope
from yeaboi.context.window import load_sprint_calendar, resolve_window, window_label

logger = logging.getLogger(__name__)

#: Source token → the ``mode`` its label rows carry.
SOURCE_MODES: dict[str, str] = {name: ("planning" if name == "plan" else name) for name in SOURCES}


@dataclass(frozen=True)
class SourceRow:
    """One candidate run, in the resolver's own shape (each store has its own date column)."""

    source: str
    session_id: str
    run_id: str  # the store's row id as text; "" for a planning/analysis session
    on_date: str  # ISO date the run is about
    created_at: str
    title: str
    project: str = ""
    tags: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return self.run_id or self.session_id


@dataclass(frozen=True)
class Selection:
    """What a resolved scope lets each source read."""

    scope: ContextScope | None
    start: str = ""  # resolved window, "" when unbounded
    end: str = ""
    by_source: Mapping[str, tuple[str, ...] | None] = field(default_factory=dict)  # None = unrestricted
    calendar_source: str = ""
    warnings: tuple[str, ...] = ()

    def ids(self, source: str) -> tuple[str, ...] | None:
        """The ids ``source`` may read, or ``None`` when it is unrestricted."""
        if self.scope is None:
            return None
        if not self.scope.wants(source):
            return ()
        return self.by_source.get(source)

    def run_ids(self, source: str) -> tuple[int, ...] | None:
        """The integer row ids the history stores take (``None`` = unrestricted)."""
        ids = self.ids(source)
        if ids is None:
            return None
        out: list[int] = []
        for value in ids:
            tail = value.rsplit(":", 1)[-1]
            if tail.isdigit():
                out.append(int(tail))
        return tuple(out)

    def wants(self, source: str) -> bool:
        return self.scope is None or self.scope.wants(source)


@dataclass(frozen=True)
class Preview:
    """The counts a picker shows before a run starts."""

    selection: Selection
    counts: dict[str, int]
    label: str
    rows: dict[str, list[SourceRow]] = field(default_factory=dict)


def resolve_scope(
    scope: ContextScope | Mapping | str | None,
    *,
    today: date | None = None,
    db_path: Path | None = None,
) -> Selection:
    """Resolve ``scope``; ``None`` (or a scope that narrows nothing) reads no store at all."""
    resolved = coerce_scope(scope)
    if resolved is None:
        return Selection(scope=None, by_source={name: None for name in SOURCES})
    return _walk(resolved, today=today or date.today(), db_path=db_path, count_all=False).selection


def preview_scope(
    scope: ContextScope | Mapping | str | None,
    *,
    today: date | None = None,
    db_path: Path | None = None,
    rows: bool = False,
) -> Preview:
    """Counts per source under ``scope`` (every source is read, even an unrestricted one)."""
    resolved = coerce_scope(scope) or ContextScope()
    return _walk(resolved, today=today or date.today(), db_path=db_path, count_all=True, keep_rows=rows)


def _walk(
    scope: ContextScope, *, today: date, db_path: Path | None, count_all: bool, keep_rows: bool = False
) -> Preview:
    from yeaboi.paths import get_db_path

    path = Path(db_path or get_db_path())
    warnings: list[str] = []
    start = end = ""
    calendar_source = ""
    if scope.window.bounded:
        calendar = None
        if scope.window.kind == "sprints":
            calendar = load_sprint_calendar(today=today, db_path=path)
            calendar_source = calendar.source
        try:
            start, end = resolve_window(scope.window, today=today, calendar=calendar)
        except (TypeError, ValueError) as exc:
            warnings.append(f"window ignored: {exc}")
            logger.warning("resolve_scope: window %r ignored: %s", scope.window, exc)
    narrows = scope.narrows
    by_source: dict[str, tuple[str, ...] | None] = {}
    counts: dict[str, int] = {}
    kept: dict[str, list[SourceRow]] = {}
    for source in SOURCES:
        if not scope.wants(source):
            by_source[source] = ()
            counts[source] = 0
            continue
        restricted = narrows and (
            bool(start or end) or bool(scope.projects or scope.tags) or scope.limit_for(source) > 0
        )
        if not restricted and not count_all:
            by_source[source] = None
            continue
        if not path.exists():
            by_source[source] = None if not restricted else ()
            counts[source] = 0
            continue
        try:
            rows = _SOURCE_READERS[source](path)
        except Exception:  # noqa: BLE001 — one unreadable store must not stop the run
            logger.warning("resolve_scope: %s could not be read — treating it as unrestricted", source, exc_info=True)
            warnings.append(f"{SOURCE_LABELS[source]} could not be read")
            by_source[source] = None
            counts[source] = 0
            continue
        selected = _select(rows, source, scope, start, end, path)
        by_source[source] = tuple(r.key for r in selected) if restricted else None
        counts[source] = len(selected)
        if keep_rows:
            kept[source] = selected
    selection = Selection(
        scope=scope,
        start=start,
        end=end,
        by_source=by_source,
        calendar_source=calendar_source,
        warnings=tuple(warnings),
    )
    summary = " · ".join(
        f"{n} {_plural(source, n)}" for source, n in counts.items() if n or scope.wants(source) and count_all
    )
    if start or end:
        summary = f"{summary} · {window_label(start, end)}" if summary else window_label(start, end)
    logger.info(
        "context: sources=%s window=%s → %s",
        "all" if scope.sources is None else ",".join(sorted(scope.sources)) or "none",
        scope.window.label(),
        summary or "nothing",
    )
    return Preview(selection=selection, counts=counts, label=summary or "nothing to read", rows=kept)


def _select(
    rows: list[SourceRow], source: str, scope: ContextScope, start: str, end: str, path: Path
) -> list[SourceRow]:
    if start or end:
        rows = [r for r in rows if r.on_date and (not start or r.on_date >= start) and (not end or r.on_date <= end)]
    if scope.projects or scope.tags:
        with LabelStore(path) as labels:
            allowed = labels.find_ids(SOURCE_MODES[source], projects=scope.projects, tags=normalize_tags(scope.tags))
        rows = [r for r in rows if r.key in allowed]
    rows = sorted(rows, key=lambda r: (r.on_date, r.created_at), reverse=True)
    cap = scope.limit_for(source)
    return rows[:cap] if cap else rows


def _plural(source: str, n: int) -> str:
    label = SOURCE_LABELS[source].lower()
    if n == 1 and label.endswith("s") and " and " not in label:
        return label[:-1]
    return label


# ── per-source readers: which store, which date column ─────────────────────


def _day(value: str) -> str:
    return (value or "")[:10]


def _sessions(path: Path, mode: str, source: str) -> list[SourceRow]:
    from yeaboi.sessions import SessionStore, make_display_name

    with SessionStore(path) as store:
        rows = store.list_sessions(mode=mode)
    return [
        SourceRow(
            source=source,
            session_id=r["session_id"],
            run_id="",
            on_date=_day(r.get("created_at", "")),
            created_at=r.get("created_at", "") or "",
            title=r.get("title") or make_display_name(r),
        )
        for r in rows
    ]


def _plan(path: Path) -> list[SourceRow]:
    return _sessions(path, "planning", "plan")


def _analysis(path: Path) -> list[SourceRow]:
    return _sessions(path, "analysis", "analysis")


def _standup(path: Path) -> list[SourceRow]:
    from yeaboi.standup.store import StandupStore

    with StandupStore(path) as store:
        rows = store.get_all_history(limit=0)
    return [
        SourceRow(
            "standup",
            r.get("session_id", ""),
            str(r["id"]),
            r.get("standup_date") or _day(r["run_at"]),
            r["run_at"],
            f"Standup — {r.get('standup_date') or _day(r['run_at'])}",
        )
        for r in rows
    ]


def _retro(path: Path) -> list[SourceRow]:
    from yeaboi.retro.store import RetroStore

    with RetroStore(path) as store:
        rows = store.get_all_history(limit=0)
    return [
        SourceRow(
            "retro",
            r.get("session_id", ""),
            str(r["id"]),
            r.get("retro_date") or _day(r["run_at"]),
            r["run_at"],
            f"Retro — {r.get('retro_date') or _day(r['run_at'])}",
            project=r.get("project_name") or "",
        )
        for r in rows
    ]


def _poker(path: Path) -> list[SourceRow]:
    from yeaboi.poker.store import PokerStore

    with PokerStore(path) as store:
        rows = store.get_all_history(limit=0)
    return [
        SourceRow(
            "poker",
            r.get("session_id", ""),
            str(r["id"]),
            r.get("poker_date") or _day(r["run_at"]),
            r["run_at"],
            f"Poker — {r.get('poker_date') or _day(r['run_at'])}",
            project=r.get("project_name") or "",
        )
        for r in rows
    ]


def _performance(path: Path) -> list[SourceRow]:
    from yeaboi.performance.store import PerformanceStore

    with PerformanceStore(path) as store:
        rows = store.get_all_history(limit=0)
    return [
        SourceRow(
            "performance",
            "",
            f"{r['kind']}:{r['id']}",
            r.get("on_date") or _day(r["created_at"]),
            r["created_at"],
            r.get("title", ""),
        )
        for r in rows
    ]


def _reporting(path: Path) -> list[SourceRow]:
    from yeaboi.reporting.store import ReportingStore

    with ReportingStore(path) as store:
        rows = store.get_all_history(limit=0)
    return [
        SourceRow(
            "reporting",
            r.get("session_id", ""),
            str(r["id"]),
            r.get("period_end") or _day(r["run_at"]),
            r["run_at"],
            f"Report — {r.get('period') or _day(r['run_at'])}",
            project=r.get("project_name") or "",
        )
        for r in rows
    ]


def _review(path: Path) -> list[SourceRow]:
    from yeaboi.solo.store import WeeklyReviewStore

    with WeeklyReviewStore(path) as store:
        rows = store.get_all_history(limit=0)
    return [
        SourceRow(
            "review",
            r.get("session_id", ""),
            str(r["id"]),
            r.get("week_end") or _day(r["run_at"]),
            r["run_at"],
            f"Week {r.get('week_label') or _day(r['run_at'])}",
            project=r.get("project_name") or "",
        )
        for r in rows
    ]


_SOURCE_READERS: dict[str, Callable[[Path], list[SourceRow]]] = {
    "plan": _plan,
    "standup": _standup,
    "retro": _retro,
    "poker": _poker,
    "performance": _performance,
    "analysis": _analysis,
    "reporting": _reporting,
    "review": _review,
}
