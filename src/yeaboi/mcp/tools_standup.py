"""MCP tools: Daily Standup (run a standup, read history, get/set the config)."""

from __future__ import annotations

import logging
import re

# Context must be importable from module globals — FastMCP evaluates the
# stringified type hints (PEP 563) of tool functions against this namespace.
from mcp.server.fastmcp import Context

from yeaboi.mcp.runtime import run_engine, run_readonly

logger = logging.getLogger(__name__)

# Defaults used when standup_config_set runs before any config exists — mirror
# the standup_config table defaults in standup/store.py.
_CONFIG_DEFAULTS = {
    "enabled": False,
    "time": "10:00",
    "weekdays": "1-5",
    "delivery_channels": ["terminal"],
    "lead_minutes": 10,
    "timezone": "",
    "repo_path": "",
    "my_aliases": "",
}


def _validated_channels(channels: list | None) -> list[str] | None:
    if not channels:
        return None
    from yeaboi.standup.delivery import ALL_CHANNELS

    bad = [c for c in channels if c not in ALL_CHANNELS]
    if bad:
        raise ValueError(f"unknown delivery channel(s) {bad} — valid: {', '.join(ALL_CHANNELS)}")
    return list(channels)


def _standup_run(session_id: str, deliver: bool, days: int, channels: list | None):
    from yeaboi.mcp.tools_sessions import resolve_session_id
    from yeaboi.standup.engine import run_standup

    resolved = resolve_session_id(session_id)
    return run_standup(resolved, deliver=deliver, days=days or None, channels=_validated_channels(channels))


def _standup_history(session_id: str, limit: int) -> dict:
    from yeaboi.mcp.tools_sessions import resolve_session_id
    from yeaboi.paths import get_db_path
    from yeaboi.standup.store import StandupStore

    resolved = resolve_session_id(session_id)
    with StandupStore(get_db_path()) as store:
        history = store.get_history(resolved, limit=limit)
        latest = store.get_latest_report(resolved)
    return {"session_id": resolved, "history": history, "latest_report": latest}


def _standup_config_get(session_id: str) -> dict:
    from yeaboi.mcp.tools_sessions import resolve_session_id
    from yeaboi.paths import get_db_path
    from yeaboi.standup.delivery import ALL_CHANNELS
    from yeaboi.standup.store import StandupStore

    resolved = resolve_session_id(session_id)
    with StandupStore(get_db_path()) as store:
        config = store.load_config(resolved)
    return {"session_id": resolved, "config": config, "valid_channels": list(ALL_CHANNELS)}


def _standup_config_set(
    session_id: str,
    enabled: bool | None,
    time: str,
    weekdays: str,
    delivery_channels: list | None,
    lead_minutes: int,
    repo_path: str | None,
    my_aliases: str | None,
) -> dict:
    from yeaboi.mcp.tools_sessions import resolve_session_id
    from yeaboi.paths import get_db_path
    from yeaboi.standup.store import StandupStore

    if time and not re.fullmatch(r"\d{1,2}:\d{2}", time):
        raise ValueError(f"time must be HH:MM (24h), got {time!r}")
    resolved = resolve_session_id(session_id)
    with StandupStore(get_db_path()) as store:
        current = store.load_config(resolved) or dict(_CONFIG_DEFAULTS)
        merged = {
            "enabled": current["enabled"] if enabled is None else enabled,
            "time": time or current["time"],
            "weekdays": weekdays or current["weekdays"],
            "delivery_channels": _validated_channels(delivery_channels) or current["delivery_channels"],
            "lead_minutes": current.get("lead_minutes", 10) if lead_minutes < 0 else lead_minutes,
            "timezone": current.get("timezone", ""),
            "repo_path": current.get("repo_path", "") if repo_path is None else repo_path,
            "my_aliases": current.get("my_aliases", "") if my_aliases is None else my_aliases,
        }
        store.save_config(resolved, **merged)
    logger.info("Standup config updated via MCP: session=%s enabled=%s", resolved, merged["enabled"])
    return {"session_id": resolved, "config": merged}


def register(app) -> None:
    """Attach the standup tools to the FastMCP app."""

    @app.tool()
    async def standup_run(
        ctx: Context,
        session_id: str = "",
        deliver: bool = False,
        days: int = 0,
        channels: list[str] | None = None,
    ) -> dict:
        """Run a Daily Standup: collect team activity (Jira/AzDO/GitHub/git/docs), score sprint
        confidence, and summarize per member. Returns the report for you to present; deliver=true
        additionally sends it to the session's configured channels (Slack/email/desktop) — ask the
        user before enabling. channels overrides the saved channels for this run (terminal,
        desktop, slack, email). days overrides the activity look-back window. Blank session_id =
        most recent session."""
        return await run_engine(ctx, _standup_run, session_id, deliver, days, channels)

    @app.tool()
    async def standup_history(session_id: str = "", limit: int = 30) -> dict:
        """Get recent Daily Standup runs for a session, including the latest full report.
        Blank session_id = most recent session."""
        return await run_readonly(_standup_history, session_id, limit)

    @app.tool()
    async def standup_config_get(session_id: str = "") -> dict:
        """Get a session's standup configuration (time, weekdays, delivery channels, aliases).
        config is null when nothing is configured yet. Blank session_id = most recent session."""
        return await run_readonly(_standup_config_get, session_id)

    @app.tool()
    async def standup_config_set(
        session_id: str = "",
        enabled: bool | None = None,
        time: str = "",
        weekdays: str = "",
        delivery_channels: list[str] | None = None,
        lead_minutes: int = -1,
        repo_path: str | None = None,
        my_aliases: str | None = None,
    ) -> dict:
        """Update a session's standup configuration; omitted fields keep their current value.
        time is HH:MM (the meeting time), weekdays like '1-5' or '1,3,5', delivery_channels from
        terminal/desktop/slack/email, my_aliases a comma-separated identity list across tools.
        NOTE: this saves the config only — installing the OS schedule (launchd/cron) is
        machine-local and done from the yeaboi TUI. Blank session_id = most recent session."""
        return await run_readonly(
            _standup_config_set,
            session_id,
            enabled,
            time,
            weekdays,
            delivery_channels,
            lead_minutes,
            repo_path,
            my_aliases,
        )
