"""MCP tools: Performance mode (roster, 1:1 prep/completion, 6-month review)."""

from __future__ import annotations

import logging

# Context must be importable from module globals — FastMCP evaluates the
# stringified type hints (PEP 563) of tool functions against this namespace.
from mcp.server.fastmcp import Context

from yeaboi.mcp.runtime import run_engine, run_readonly

logger = logging.getLogger(__name__)


def _roster(jira_project: str, azdo_project: str):
    from yeaboi.performance.roster import fetch_roster

    return {"engineers": fetch_roster(jira_project=jira_project, azdo_project=azdo_project)}


def _one_on_one_prep(engineer: str, session_id: str, jira_project: str, azdo_project: str):
    from yeaboi.performance.engine import run_one_on_one_prep

    return run_one_on_one_prep(
        engineer,
        session_id=session_id,
        jira_project=jira_project,
        azdo_project=azdo_project,
    )


def _one_on_one_complete(
    engineer: str, transcript: str, session_id: str, deliver: bool, recipients: list | None, images: list | None
):
    if not transcript.strip():
        raise ValueError("transcript is required — the 1:1 notes or transcript text.")
    from yeaboi.performance.engine import complete_one_on_one

    return complete_one_on_one(
        engineer,
        transcript,
        session_id=session_id,
        deliver=deliver,
        recipients=recipients or None,
        images=tuple(images or ()),
    )


def _note_add(engineer: str, note_text: str) -> dict:
    if not engineer.strip():
        raise ValueError("engineer is required — a name from perf_roster.")
    if not note_text.strip():
        raise ValueError("note_text is required — the observation to record.")
    from yeaboi.paths import get_db_path
    from yeaboi.performance.store import PerformanceStore

    with PerformanceStore(get_db_path()) as store:
        note_id = store.add_note(engineer.strip(), note_text.strip())
    return {"engineer": engineer.strip(), "note_id": note_id}


def _six_month_review(engineer: str, period_months: int, session_id: str, jira_project: str, azdo_project: str):
    from yeaboi.performance.engine import run_six_month_review

    return run_six_month_review(
        engineer,
        session_id=session_id,
        jira_project=jira_project,
        azdo_project=azdo_project,
        period_months=period_months,
    )


def register(app) -> None:
    """Attach the performance tools to the FastMCP app."""

    @app.tool()
    async def perf_roster(jira_project: str = "", azdo_project: str = "") -> dict:
        """List the engineer roster derived from recent Jira/Azure DevOps assignees —
        the engineer names the other perf_* tools accept."""
        return await run_readonly(_roster, jira_project, azdo_project)

    @app.tool()
    async def perf_one_on_one_prep(
        engineer: str,
        ctx: Context,
        session_id: str = "",
        jira_project: str = "",
        azdo_project: str = "",
    ) -> dict:
        """Prepare a 1:1 for an engineer: talking points, feedback, goals and growth areas from
        their recent tickets plus open action items from the previous 1:1."""
        return await run_engine(ctx, _one_on_one_prep, engineer, session_id, jira_project, azdo_project)

    @app.tool()
    async def perf_one_on_one_complete(
        engineer: str,
        transcript: str,
        ctx: Context,
        session_id: str = "",
        deliver: bool = False,
        recipients: list[str] | None = None,
        images: list[str] | None = None,
    ) -> dict:
        """Complete a held 1:1 from its notes/transcript: produces a summary and tracked action
        items (carried into the next prep). images takes local file paths of photographed notes
        to include in the multimodal call. deliver=true emails the summary via the configured
        SMTP — ask the user before enabling."""
        return await run_engine(
            ctx, _one_on_one_complete, engineer, transcript, session_id, deliver, recipients, images
        )

    @app.tool()
    async def perf_note_add(engineer: str, note_text: str) -> dict:
        """Record a free-text note about an engineer (an observation, kudos, a concern).
        Notes feed the next 1:1 prep and the periodic review for that engineer."""
        return await run_readonly(_note_add, engineer, note_text)

    @app.tool()
    async def perf_six_month_review(
        engineer: str,
        ctx: Context,
        period_months: int = 6,
        session_id: str = "",
        jira_project: str = "",
        azdo_project: str = "",
    ) -> dict:
        """Draft an engineer's periodic performance review from past 1:1s, delivery history and
        the competency framework (bundled default, or PERFORMANCE_FRAMEWORK_PATH)."""
        return await run_engine(ctx, _six_month_review, engineer, period_months, session_id, jira_project, azdo_project)
