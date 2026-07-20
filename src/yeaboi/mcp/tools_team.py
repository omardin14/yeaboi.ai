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


def _compare_plan_to_actuals(session_id: str, source: str, project_key: str) -> dict:
    import json

    from yeaboi.tools.team_learning import compare_plan_to_actuals

    # A LangChain @tool — .invoke() runs the underlying function; it returns
    # a JSON string (all yeaboi tools do, for the agent loop).
    raw = compare_plan_to_actuals.invoke({"session_id": session_id, "source": source, "project_key": project_key})
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {"raw": raw}


def register(app) -> None:
    """Attach the team-learning tools to the FastMCP app."""

    @app.tool()
    async def team_profile_get() -> dict:
        """Get stored team calibration profiles (velocity, estimation accuracy, completion rate)
        learned from tracker history via yeaboi --learn."""
        return await run_readonly(_team_profile_get)

    @app.tool()
    async def team_compare_plan_to_actuals(session_id: str = "", source: str = "", project_key: str = "") -> dict:
        """Compare a generated plan to actual sprint outcomes from the tracker: estimated vs
        actual points, planned vs actual sprints, added/removed stories, cycle times. Blank
        session_id = most recent session; source: 'jira' or 'azdo' (auto-detected when blank)."""
        return await run_readonly(_compare_plan_to_actuals, session_id, source, project_key)
