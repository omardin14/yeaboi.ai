"""MCP tools: Daily Standup (history now; standup_run wired in the LLM-tools commit)."""

from __future__ import annotations

import logging

from yeaboi.mcp.runtime import run_readonly

logger = logging.getLogger(__name__)


def _standup_history(session_id: str, limit: int) -> dict:
    from yeaboi.mcp.tools_sessions import resolve_session_id
    from yeaboi.paths import get_db_path
    from yeaboi.standup.store import StandupStore

    resolved = resolve_session_id(session_id)
    with StandupStore(get_db_path()) as store:
        history = store.get_history(resolved, limit=limit)
        latest = store.get_latest_report(resolved)
    return {"session_id": resolved, "history": history, "latest_report": latest}


def register(app) -> None:
    """Attach the standup tools to the FastMCP app."""

    @app.tool()
    async def standup_history(session_id: str = "", limit: int = 30) -> dict:
        """Get recent Daily Standup runs for a session, including the latest full report.
        Blank session_id = most recent session."""
        return await run_readonly(_standup_history, session_id, limit)
