"""MCP tools: team-learning reads (calibration profiles)."""

from __future__ import annotations

import logging

from yeaboi.mcp.runtime import run_readonly

logger = logging.getLogger(__name__)


def _team_profile_get() -> dict:
    from yeaboi.paths import get_db_path
    from yeaboi.team_profile import TeamProfileStore

    db_path = get_db_path()
    if not db_path.exists():
        return {"profiles": []}
    with TeamProfileStore(db_path) as store:
        profiles = store.list_profiles()
    return {"profiles": profiles}


def register(app) -> None:
    """Attach the team-learning tools to the FastMCP app."""

    @app.tool()
    async def team_profile_get() -> dict:
        """Get stored team calibration profiles (velocity, estimation accuracy, completion rate)
        learned from tracker history via yeaboi --learn."""
        return await run_readonly(_team_profile_get)
