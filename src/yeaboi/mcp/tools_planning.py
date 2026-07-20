"""MCP tools: the planning pipeline (intake contract, plan read/export/generate)."""

from __future__ import annotations

import dataclasses
import json
import logging

from yeaboi.mcp.runtime import run_readonly

logger = logging.getLogger(__name__)


def _intake_questions() -> dict:
    from yeaboi.prompts.intake import (
        ESSENTIAL_QUESTIONS,
        INTAKE_QUESTIONS,
        PHASE_LABELS,
        QUESTION_DEFAULTS,
        QUESTION_METADATA,
        SMART_ESSENTIALS,
    )

    return {
        "questions": {str(number): text for number, text in INTAKE_QUESTIONS.items()},
        "defaults": {str(number): value for number, value in QUESTION_DEFAULTS.items()},
        "choice_metadata": {str(number): dataclasses.asdict(meta) for number, meta in QUESTION_METADATA.items()},
        "phases": PHASE_LABELS,
        "essential_questions": sorted(ESSENTIAL_QUESTIONS),
        "smart_essentials": sorted(SMART_ESSENTIALS),
        "usage": (
            "Ask the user the smart_essentials questions conversationally (plus Q1, the project "
            "description), then call plan_generate with the collected answers keyed by question "
            "number. Unanswered questions fall back to `defaults`."
        ),
    }


def _load_state(session_id: str) -> tuple[str, dict]:
    from yeaboi.mcp.tools_sessions import resolve_session_id
    from yeaboi.paths import get_db_path
    from yeaboi.sessions import SessionStore

    resolved = resolve_session_id(session_id)
    with SessionStore(get_db_path()) as store:
        state = store.load_state(resolved)
    if state is None:
        raise ValueError(f"Session not found or has no saved state: {resolved}")
    return resolved, state


def _plan_get(session_id: str) -> dict:
    from yeaboi.json_exporter import export_plan_json

    resolved, state = _load_state(session_id)
    plan = json.loads(export_plan_json(state))
    plan["session_id"] = resolved
    return plan


def _plan_export(session_id: str, format: str) -> dict:
    resolved, state = _load_state(session_id)
    if format == "html":
        from yeaboi.html_exporter import export_plan_html

        path = export_plan_html(state)
    elif format == "markdown":
        from yeaboi.repl._io import _export_plan_markdown

        path = _export_plan_markdown(state)
    else:
        raise ValueError(f"Unsupported format {format!r} — use 'markdown' or 'html'.")
    logger.info("Plan exported via MCP: session=%s format=%s path=%s", resolved, format, path)
    return {"session_id": resolved, "format": format, "path": str(path)}


def register(app) -> None:
    """Attach the planning tools to the FastMCP app."""

    @app.tool()
    async def intake_questions() -> dict:
        """Get yeaboi's intake contract: the 30 planning questions, which are essential, their
        defaults and choice options. Call this before gathering answers for plan_generate."""
        return await run_readonly(_intake_questions)

    @app.tool()
    async def plan_get(session_id: str = "") -> dict:
        """Get a saved sprint plan as JSON (analysis, epics, stories, tasks, sprints).
        Blank session_id = most recent session."""
        return await run_readonly(_plan_get, session_id)

    @app.tool()
    async def plan_export(session_id: str = "", format: str = "markdown") -> dict:
        """Export a saved plan to a file (format: 'markdown' or 'html') and return its path.
        Blank session_id = most recent session."""
        return await run_readonly(_plan_export, session_id, format)
