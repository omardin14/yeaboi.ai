"""The two cross-mode reads a scope narrows most often.

Kept apart from :mod:`yeaboi.context.scope` so that module stays pure and
import-free. Both never raise — a broken store reads as "nothing to feed".
"""

from __future__ import annotations

import logging
from pathlib import Path

from yeaboi.context.resolve import Selection

logger = logging.getLogger(__name__)


def latest_planning_state(selection: Selection | None, *, db_path: Path | None = None) -> tuple[str, dict] | None:
    """The newest selected planning session that carries a sprint plan.

    ``None`` for an unscoped selection (the caller keeps its own default) or
    when the selection does not want plans; sessions without ``sprints`` are
    skipped. Returns ``(session_id, state)``.
    """
    if selection is None or selection.scope is None or not selection.wants("plan"):
        return None
    ids = selection.ids("plan")
    try:
        from yeaboi.paths import get_db_path
        from yeaboi.sessions import SessionStore

        path = db_path or get_db_path()
        if not Path(path).exists():
            return None
        with SessionStore(path) as store:
            candidates = (
                list(ids) if ids is not None else [r["session_id"] for r in store.list_sessions(mode="planning")]
            )
            for sid in candidates:
                state = store.load_state(sid)
                if state and state.get("sprints"):
                    logger.info("latest_planning_state: session=%s", sid)
                    return sid, state
    except Exception:  # noqa: BLE001 — the same never-raise contract as resolve_scope
        logger.debug("latest_planning_state failed (non-fatal)", exc_info=True)
    return None


def recent_standup_blockers(selection: Selection | None, *, limit: int = 10, db_path: Path | None = None) -> list[str]:
    """Blockers from the selected standups, newest first, deduped as ``name: blocker``.

    Feeds the standup→retro edge. An unscoped selection returns nothing (the
    team-wide board keeps its carry-forward-only seeding), and so does one
    with standups switched off.
    """
    if selection is None or selection.scope is None or not selection.wants("standup"):
        return []
    try:
        from yeaboi.paths import get_db_path
        from yeaboi.standup.store import StandupStore

        path = db_path or get_db_path()
        if not Path(path).exists():
            return []
        with StandupStore(path) as store:
            reports = store.get_recent_reports(limit, run_ids=selection.run_ids("standup"))
    except Exception:  # noqa: BLE001
        logger.debug("recent_standup_blockers failed (non-fatal)", exc_info=True)
        return []
    seen: set[str] = set()
    blockers: list[str] = []
    for report in reports:
        for member in report.member_updates:
            text = (member.blockers or "").strip()
            if not text or text.lower() in seen:
                continue
            seen.add(text.lower())
            blockers.append(f"{member.name}: {text}" if member.name else text)
    logger.info("recent_standup_blockers: reports=%d blockers=%d", len(reports), len(blockers))
    return blockers
