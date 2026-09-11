"""The cross-mode recent-sessions list.

``sessions_meta`` holds planning and analysis sessions only; every other
mode's runs live in its own store. This module unions every store that lists
its runs into one newest-first list, so the TUI, the desktop's home and the
``/api/sessions/recent`` route read one function. A mode with no listing is
simply absent — no rows are invented.

Wire mode keys: ``planning``, ``analysis``, ``standup``, ``retro``,
``reporting``, ``ship``, ``review``, ``poker``, ``performance``, ``roadmap``,
``agent-usage``, ``agent-advisor``, ``agent-security``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: Every mode key a row can carry, in the order the adapters run.
MODES: tuple[str, ...] = (
    "planning",
    "analysis",
    "standup",
    "retro",
    "reporting",
    "ship",
    "review",
    "poker",
    "performance",
    "roadmap",
    "agent-usage",
    "agent-advisor",
    "agent-security",
)

# How many rows each store is asked for when the caller sets no limit.
_STORE_LIMIT = 100

# Which label-store mode a row's labels are filed under (agent reports carry none).
_LABEL_MODES = {
    "planning": "planning",
    "analysis": "analysis",
    "standup": "standup",
    "retro": "retro",
    "reporting": "reporting",
    "review": "review",
    "poker": "poker",
    "performance": "performance",
}


@dataclass(frozen=True)
class RecentSession:
    """One run or session, whichever store it came from."""

    session_id: str
    run_id: str  # the store's own row id; "" for a planning/analysis session
    mode: str
    title: str
    created_at: str
    last_modified: str
    subtitle: str = ""  # the hub's second line, "" when the store has none
    kind: str = ""  # the artifact kind where one mode keeps several (performance)
    project_label: str = ""
    tags: tuple[str, ...] = ()
    engineer: str = ""


def recent_sessions(
    *,
    limit: int = 20,
    mode: str = "",
    project_label: str = "",
    db_path: Path | None = None,
) -> list[RecentSession]:
    """The newest runs across every mode, optionally narrowed to one mode or one project label.

    A store that cannot be read is skipped with a warning. ``limit`` 0 means
    every row.
    """
    from yeaboi.paths import get_db_path

    path = db_path or get_db_path()
    if not Path(path).exists():
        return []
    if mode and mode not in MODES:
        raise ValueError(f"unknown mode {mode!r} — one of {', '.join(MODES)}")

    per_store = limit if limit > 0 and not project_label else _STORE_LIMIT
    rows: list[RecentSession] = []
    for name, adapter in _ADAPTERS.items():
        if mode and mode != name:
            continue
        try:
            rows.extend(adapter(path, per_store))
        except Exception:  # noqa: BLE001 — one unreadable store must not empty the list
            logger.warning("recent_sessions: %s listing failed", name, exc_info=True)
    rows = _with_labels(path, rows)
    if project_label:
        rows = [row for row in rows if row.project_label == project_label]
    rows.sort(key=lambda r: r.last_modified, reverse=True)
    if limit > 0:
        rows = rows[:limit]
    logger.info("recent_sessions: %d row(s) (mode=%s label=%s)", len(rows), mode or "-", project_label or "-")
    return rows


def _with_labels(path: Path, rows: list[RecentSession]) -> list[RecentSession]:
    """Fill each row's project label and tags from the label store, in one read."""
    from dataclasses import replace

    from yeaboi.context.labels import LabelStore

    try:
        with LabelStore(path) as store:
            labels = store.list_labels(limit=0)
    except Exception:  # noqa: BLE001 — the list renders without labels
        logger.warning("recent_sessions: labels could not be read", exc_info=True)
        return rows
    by_key = {(row.mode, row.session_id, row.run_id): row for row in labels}
    out = []
    for row in rows:
        label_mode = _LABEL_MODES.get(row.mode)
        label = by_key.get((label_mode, row.session_id, row.run_id)) if label_mode else None
        if label is None and label_mode and row.run_id:
            # A run labelled by its row id alone (the store's write side keys it so).
            label = by_key.get((label_mode, "", row.run_id))
        if label is None:
            out.append(row)
        else:
            out.append(replace(row, project_label=label.project, tags=tuple(label.tags)))
    return out


Adapter = Callable[[Path, int], list[RecentSession]]


def _meta_sessions(path: Path, limit: int, mode: str) -> list[RecentSession]:
    """Planning and analysis rows straight from ``sessions_meta``."""
    from yeaboi.sessions import SessionStore, make_display_name

    with SessionStore(path) as store:
        rows = store.list_sessions(mode=mode, limit=limit)
    return [
        RecentSession(
            session_id=row["session_id"],
            run_id="",
            mode=mode,
            title=row.get("title") or make_display_name(row),
            created_at=row["created_at"] or "",
            last_modified=row["last_modified"] or "",
            subtitle=_node_label(row.get("last_node_completed") or ""),
        )
        for row in rows
    ]


# What a planning row's second line says for the newest finished build step.
_NODE_DONE = {
    "project_analyzer": "Analysed",
    "epic_review": "Epic formatted",
    "feature_generator": "Features generated",
    "feature_skip": "Features generated",
    "story_writer": "Stories written",
    "task_decomposer": "Tasks broken down",
    "sprint_planner": "Sprints planned",
}


def _node_label(node: str) -> str:
    return _NODE_DONE.get(node, "")


def _planning(path, limit):
    return _meta_sessions(path, limit, "planning")


def _analysis(path, limit):
    return _meta_sessions(path, limit, "analysis")


def _standup(path, limit):
    from yeaboi.standup.store import StandupStore

    with StandupStore(path) as store:
        rows = store.get_all_history(limit)
    return [
        RecentSession(
            session_id=r.get("session_id", ""),
            run_id=str(r["id"]),
            mode="standup",
            title=f"Standup — {r.get('standup_date') or r['run_at'][:10]}",
            created_at=r["run_at"],
            last_modified=r["run_at"],
            subtitle=_standup_subtitle(r),
        )
        for r in rows
    ]


def _standup_subtitle(row: dict) -> str:
    parts = []
    if row.get("sprint_day"):
        parts.append(f"sprint day {row['sprint_day']}")
    if row.get("confidence_pct") is not None and row.get("confidence_pct") != "":
        parts.append(f"{row['confidence_pct']}% confidence")
    return " · ".join(parts)


def _retro(path, limit):
    from yeaboi.retro.store import RetroStore

    with RetroStore(path) as store:
        rows = store.get_all_history(limit)
    return [
        RecentSession(
            session_id=r.get("session_id", ""),
            run_id=str(r["id"]),
            mode="retro",
            title=f"Retro — {r.get('retro_date') or r['run_at'][:10]}",
            created_at=r["run_at"],
            last_modified=r["run_at"],
            subtitle=f"{r['card_count']} cards" if r.get("card_count") else "",
        )
        for r in rows
    ]


def _reporting(path, limit):
    from yeaboi.reporting.store import ReportingStore

    with ReportingStore(path) as store:
        rows = store.get_all_history(limit)
    return [
        RecentSession(
            session_id=r.get("session_id", ""),
            run_id=str(r["id"]),
            mode="reporting",
            title=f"Report — {r.get('period') or r['run_at'][:10]}",
            created_at=r["run_at"],
            last_modified=r["run_at"],
            subtitle=f"{r['item_count']} items" if r.get("item_count") else "",
        )
        for r in rows
    ]


def _ship(path, limit):
    from yeaboi.ship.store import ShipStore

    with ShipStore(path) as store:
        runs = store.list_runs(limit=limit)
    return [
        RecentSession(
            session_id=run.session_id,
            run_id=run.run_id,
            mode="ship",
            title=f"Ship — {run.item_id or run.run_id} · {run.status}",
            created_at=run.created_at,
            last_modified=run.updated_at or run.created_at,
            subtitle=run.status,
        )
        for run in runs
    ]


def _review(path, limit):
    from yeaboi.solo.store import WeeklyReviewStore

    with WeeklyReviewStore(path) as store:
        rows = store.get_all_history(limit)
    return [
        RecentSession(
            session_id=r.get("session_id", ""),
            run_id=str(r["id"]),
            mode="review",
            title=f"Week {r.get('week_label') or r['run_at'][:10]}",
            created_at=r["run_at"],
            last_modified=r["run_at"],
            subtitle=f"{r['action_count']} actions" if r.get("action_count") else "",
        )
        for r in rows
    ]


def _poker(path, limit):
    from yeaboi.poker.store import PokerStore

    with PokerStore(path) as store:
        rows = store.get_all_history(limit)
    return [
        RecentSession(
            session_id=r.get("session_id", ""),
            run_id=str(r["id"]),
            mode="poker",
            title=f"Poker — {r.get('poker_date') or r['run_at'][:10]}",
            created_at=r["run_at"],
            last_modified=r["run_at"],
            subtitle=" · ".join(
                part
                for part in (
                    r.get("scope_label") or "",
                    f"{r.get('estimated_count', 0)}/{r.get('ticket_count', 0)} estimated"
                    if r.get("ticket_count")
                    else "",
                )
                if part
            ),
        )
        for r in rows
    ]


def _performance(path, limit):
    from yeaboi.performance.store import PerformanceStore

    with PerformanceStore(path) as store:
        rows = store.get_all_history(limit)
    return [
        RecentSession(
            session_id="",
            # Three tables share the mode; the label store keys them the same way.
            run_id=f"{r['kind']}:{r['id']}",
            mode="performance",
            title=r["title"],
            created_at=r["created_at"],
            last_modified=r["created_at"],
            subtitle=r.get("engineer", ""),
            kind=r["kind"],
            engineer=r.get("engineer", ""),
        )
        for r in rows
    ]


def _roadmap(path, limit):
    from yeaboi.roadmap.store import RoadmapStore

    with RoadmapStore(path) as store:
        rows = store.list_roadmaps()
    return [
        RecentSession(
            session_id="",
            run_id=str(r["id"]),
            mode="roadmap",
            title=r["label"],
            created_at=r["created_at"] or "",
            last_modified=r["updated_at"] or r["created_at"] or "",
            subtitle=" · ".join(
                part
                for part in (
                    f"{r['project_count']} projects" if r.get("project_count") else "",
                    r.get("source_label") or "",
                )
                if part
            ),
        )
        for r in rows[:limit]
    ]


def _agent_reports(path: Path, limit: int, kind: str, mode: str, word: str) -> list[RecentSession]:
    from yeaboi.agentwatch.store import AgentWatchStore

    with AgentWatchStore(path) as store:
        rows = store.list_reports(kind, limit=limit)
    return [
        RecentSession(
            session_id="",
            run_id=str(r["id"]),
            mode=mode,
            title=f"{word} — {r.get('key_date') or r['created_at'][:10]}",
            created_at=r["created_at"],
            last_modified=r["created_at"],
        )
        for r in rows
    ]


def _agent_usage(path, limit):
    return _agent_reports(path, limit, "usage", "agent-usage", "Agent usage")


def _agent_advisor(path, limit):
    return _agent_reports(path, limit, "advisor", "agent-advisor", "Agent advisor")


def _agent_security(path, limit):
    return _agent_reports(path, limit, "security", "agent-security", "Agent security")


_ADAPTERS: dict[str, Adapter] = {
    "planning": _planning,
    "analysis": _analysis,
    "standup": _standup,
    "retro": _retro,
    "reporting": _reporting,
    "ship": _ship,
    "review": _review,
    "poker": _poker,
    "performance": _performance,
    "roadmap": _roadmap,
    "agent-usage": _agent_usage,
    "agent-advisor": _agent_advisor,
    "agent-security": _agent_security,
}
