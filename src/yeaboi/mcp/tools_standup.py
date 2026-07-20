"""MCP tools: Daily Standup (run a standup, read history)."""

from __future__ import annotations

import logging

# Context must be importable from module globals — FastMCP evaluates the
# stringified type hints (PEP 563) of tool functions against this namespace.
from mcp.server.fastmcp import Context

from yeaboi.mcp.runtime import run_engine, run_readonly

logger = logging.getLogger(__name__)


def _standup_run(session_id: str, deliver: bool, days: int):
    from yeaboi.mcp.tools_sessions import resolve_session_id
    from yeaboi.standup.engine import run_standup

    resolved = resolve_session_id(session_id)
    return run_standup(resolved, deliver=deliver, days=days or None)


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
    async def standup_run(
        ctx: Context,
        session_id: str = "",
        deliver: bool = False,
        days: int = 0,
    ) -> dict:
        """Run a Daily Standup: collect team activity (Jira/AzDO/GitHub/git/docs), score sprint
        confidence, and summarize per member. Returns the report for you to present; deliver=true
        additionally sends it to the session's configured channels (Slack/email/desktop) — ask the
        user before enabling. days overrides the activity look-back window. Blank session_id =
        most recent session."""
        return await run_engine(ctx, _standup_run, session_id, deliver, days)

    @app.tool()
    async def standup_history(session_id: str = "", limit: int = 30) -> dict:
        """Get recent Daily Standup runs for a session, including the latest full report.
        Blank session_id = most recent session."""
        return await run_readonly(_standup_history, session_id, limit)
