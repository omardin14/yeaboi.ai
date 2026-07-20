"""MCP tools: Reporting mode (business-friendly delivery reports)."""

from __future__ import annotations

import logging

# Context must be importable from module globals — FastMCP evaluates the
# stringified type hints (PEP 563) of tool functions against this namespace.
from mcp.server.fastmcp import Context

from yeaboi.mcp.runtime import run_engine

logger = logging.getLogger(__name__)

_PERIODS = ("last_sprint", "last_month", "quarter")


def _report_delivery(
    period: str,
    session_id: str,
    jira_project: str,
    azdo_project: str,
    window_start: str,
    window_end: str,
    sprint_names: list | None,
    period_label_override: str,
):
    if period not in _PERIODS:
        raise ValueError(f"period must be one of {', '.join(_PERIODS)} — got {period!r}")
    from yeaboi.reporting.engine import run_delivery_report

    return run_delivery_report(
        period,
        session_id=session_id,
        jira_project=jira_project,
        azdo_project=azdo_project,
        window_start=window_start,
        window_end=window_end,
        sprint_names=tuple(sprint_names or ()),
        period_label_override=period_label_override,
    )


def register(app) -> None:
    """Attach the reporting tools to the FastMCP app."""

    @app.tool()
    async def report_delivery(
        ctx: Context,
        period: str = "last_month",
        session_id: str = "",
        jira_project: str = "",
        azdo_project: str = "",
        window_start: str = "",
        window_end: str = "",
        sprint_names: list[str] | None = None,
        period_label_override: str = "",
    ) -> dict:
        """Generate a stakeholder-friendly delivery report of completed work from the team's
        tracker (Jira/Azure DevOps): executive summary, outcome themes, metrics, highlights.
        period: 'last_sprint', 'last_month', or 'quarter'. For 'quarter', optionally frame the
        window explicitly: window_start/window_end (YYYY-MM-DD) bound the reporting span,
        sprint_names lists the sprints it covers, and period_label_override renames the period
        (e.g. 'Q3 2026'). Blank session_id = most recent session (sprint length/project name)."""
        return await run_engine(
            ctx,
            _report_delivery,
            period,
            session_id,
            jira_project,
            azdo_project,
            window_start,
            window_end,
            sprint_names,
            period_label_override,
        )
