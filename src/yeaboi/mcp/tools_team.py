"""MCP tools: team-learning (calibration profiles + full board analysis)."""

from __future__ import annotations

import logging

# Context must be importable from module globals — FastMCP evaluates the
# stringified type hints (PEP 563) of tool functions against this namespace.
from mcp.server.fastmcp import Context

from yeaboi.mcp.runtime import run_engine, run_readonly

logger = logging.getLogger(__name__)


def _team_analyze(source: str, project_key: str, sprint_count: int, generate_samples: bool, include_insights: bool):
    from yeaboi.analysis import run_team_analysis

    return run_team_analysis(
        source=source,
        project_key=project_key,
        sprint_count=sprint_count,
        generate_samples=generate_samples,
        include_insights=include_insights,
    )


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
    async def team_analyze(
        ctx: Context,
        source: str = "",
        project_key: str = "",
        sprint_count: int = 8,
        generate_samples: bool = False,
        include_insights: bool = True,
    ) -> dict:
        """Analyse the team's tracker history (closed sprints) into a calibration profile:
        velocity, story-point calibration, writing style, DoD signals, plus coaching insights
        and headline stats. The profile is saved and feeds future planning. HEAVY: several LLM
        calls plus tracker API paging — takes minutes; warn the user before running.
        source: 'jira' or 'azdevops' (blank auto-detects); generate_samples additionally drafts
        sample tickets in the team's style (more LLM calls)."""
        return await run_engine(
            ctx, _team_analyze, source, project_key, sprint_count, generate_samples, include_insights
        )

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
