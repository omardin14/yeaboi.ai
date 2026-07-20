"""MCP tools: the planning pipeline (intake contract, plan read/export/generate)."""

from __future__ import annotations

import dataclasses
import json
import logging

import anyio

# Context must be importable from module globals — FastMCP evaluates the
# stringified type hints (PEP 563) of tool functions against this namespace.
from mcp.server.fastmcp import Context

from yeaboi.mcp.runtime import run_engine, run_readonly

logger = logging.getLogger(__name__)

# The auto-driven pipeline takes ~7 graph steps (confirm, analyzer, epics,
# stories, tasks, sprints, occasionally a capacity re-plan) — used as the
# progress denominator reported to the client.
_EXPECTED_PIPELINE_STEPS = 8


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


def _build_questionnaire(
    description: str,
    answers: dict | None,
    team_size: int,
    sprint_length_weeks: int,
    project_context: str,
):
    """Merge the tool's inputs into a confirmed-ready QuestionnaireState.

    Mirrors cli._run_headless: explicit answers win, then the convenience
    params, then keywords deterministically extracted from project_context
    (no LLM), then QUESTION_DEFAULTS via build_questionnaire_from_answers.
    """
    from yeaboi.questionnaire_io import build_questionnaire_from_answers

    if not description.strip():
        raise ValueError("description is required — a few sentences about the project.")

    merged: dict[int, str] = {1: description}
    if team_size:
        merged[6] = str(team_size)
    if sprint_length_weeks:
        merged[8] = str(sprint_length_weeks)

    # Deterministic keyword extraction fills gaps (tech stack, integrations,
    # infra) from free-form context — same mechanism the SCRUM.md file uses.
    if project_context.strip():
        try:
            from yeaboi.agent.nodes import _keyword_extract_fallback

            extracted: dict[int, str] = {}
            _keyword_extract_fallback(f"{description}\n{project_context}", extracted)
            for number, answer in extracted.items():
                merged.setdefault(number, answer)
        except Exception:
            logger.warning("project_context keyword extraction failed (continuing)", exc_info=True)

    # Explicit answers always win — the host agent gathered these from the user.
    for key, value in (answers or {}).items():
        try:
            number = int(key)
        except (TypeError, ValueError):
            raise ValueError(f"answers keys must be question numbers 1-30, got {key!r}") from None
        if not 1 <= number <= 30:
            raise ValueError(f"answers keys must be question numbers 1-30, got {number}")
        merged[number] = str(value)

    return build_questionnaire_from_answers(merged)


def _plan_generate(
    description: str,
    answers: dict | None,
    team_size: int,
    sprint_length_weeks: int,
    project_context: str,
    on_progress,
) -> dict:
    from yeaboi.agent.headless import run_planning_pipeline
    from yeaboi.json_exporter import export_plan_json

    questionnaire = _build_questionnaire(description, answers, team_size, sprint_length_weeks, project_context)
    state = run_planning_pipeline(questionnaire, on_progress=on_progress)
    plan = json.loads(export_plan_json(state))
    plan["session_id"] = state.get("_session_id", "")
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
    async def plan_generate(
        description: str,
        ctx: Context,
        answers: dict | None = None,
        team_size: int = 0,
        sprint_length_weeks: int = 0,
        project_context: str = "",
    ) -> dict:
        """Generate a full sprint plan (analysis, epics, stories, tasks, sprints) from a project
        description. Gather the intake_questions smart_essentials from the user first and pass
        them as `answers` {question_number: answer}; `project_context` takes free-form notes
        (tech stack, constraints, goals). Takes a few minutes — several LLM calls. The plan is
        saved as a session (see data.session_id) for plan_get/plan_export and the other modes."""

        def report(node_name: str, step: int) -> None:
            # Called from the engine's worker thread — bridge the async
            # progress notification back to the server's event loop.
            try:
                anyio.from_thread.run(ctx.report_progress, step, _EXPECTED_PIPELINE_STEPS, node_name)
            except Exception:
                logger.debug("progress report failed (continuing)", exc_info=True)

        return await run_engine(
            ctx,
            _plan_generate,
            description,
            answers,
            team_size,
            sprint_length_weeks,
            project_context,
            report,
        )

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
