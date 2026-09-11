"""The plan as structured data — what a blueprint drawer draws.

Every section of the plan (the intake answers, the analysis, the epic, the
features, stories, tasks and sprints) as text and numbers, each with a status
derived from the same state the stage machine (:mod:`chat_session`) routes
on. Pure: a function of graph state and the version counts a store hands
over, so a route, an export and a test all read one shape.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, is_dataclass
from enum import Enum

from yeaboi.agent.chat_session import (
    EPIC_REVIEW_NODE,
    PIPELINE_STEPS,
    PROGRESS_DONE_KEYS,
    SECTION_KINDS,
    at_intake_summary,
    questionnaire,
    stage_of,
)

logger = logging.getLogger(__name__)

#: What a section is called on every surface.
SECTION_TITLES: dict[str, str] = {
    "intake": "Your answers",
    "analysis": "Analysis",
    "epic": "Epic",
    "features": "Features",
    "stories": "Stories",
    "tasks": "Tasks",
    "sprints": "Sprints",
}

#: A section's status, in the order it moves through them.
STATUSES = ("empty", "generating", "awaiting_review", "accepted")

#: How an intake answer was obtained — the terminal's four-way tag, plus ""
#: for a question the run has not reached.
INTAKE_SOURCES = ("answered", "from description", "default", "skipped", "")

# The node that produces each artifact section.
_SECTION_NODES = {
    "analysis": "project_analyzer",
    "epic": EPIC_REVIEW_NODE,
    "features": "feature_generator",
    "stories": "story_writer",
    "tasks": "task_decomposer",
    "sprints": "sprint_planner",
}

# What the build checklist says while a step runs (repl/_ui says the same).
_STEP_LABELS = {
    "project_analyzer": "Analysing project",
    EPIC_REVIEW_NODE: "Formatting epic",
    "feature_generator": "Generating features",
    "story_writer": "Writing user stories",
    "task_decomposer": "Breaking down tasks",
    "sprint_planner": "Planning sprints",
}

# The tracker key maps a synced plan carries.
_SYNC_KEYS = (
    "jira_epic_key",
    "jira_feature_keys",
    "jira_story_keys",
    "jira_task_keys",
    "jira_sprint_keys",
    "azdevops_epic_id",
    "azdevops_story_keys",
    "azdevops_task_keys",
    "azdevops_iteration_keys",
    "linear_story_keys",
    "linear_story_ids",
    "linear_task_keys",
    "linear_cycle_keys",
    "trello_story_keys",
    "trello_task_keys",
    "trello_list_keys",
)

_PHASE_PREFIX = re.compile(r"^Phase \d+a?: ")


def section_status(state: dict, kind: str, *, running: str = "") -> str:
    """One of :data:`STATUSES` for a section; ``running`` names the node mid-turn."""
    if kind == "intake":
        qs = questionnaire(state)
        if qs is None:
            return "empty"
        if at_intake_summary(state):
            return "awaiting_review"
        return "accepted" if qs.completed else "generating"
    node = _SECTION_NODES.get(kind)
    if node is None:
        raise ValueError(f"unknown plan section {kind!r}")
    pending = state.get("pending_review", "")
    if kind == "features" and running == "feature_skip":
        running = node
    if kind == "features" and pending == "feature_skip":
        pending = node
    if kind == "epic" and not state.get("project_analysis"):
        return "empty"
    if running == node:
        return "generating"
    if pending == node:
        return "awaiting_review"
    return "accepted" if state.get(PROGRESS_DONE_KEYS[node]) else "empty"


def pipeline_progress(state: dict, *, running: str = "") -> dict:
    """The build checklist: every step with its status, and where the build is."""
    steps = []
    for node in PIPELINE_STEPS:
        if state.get(PROGRESS_DONE_KEYS[node]):
            status = "done"
        elif running == node or (node == "feature_generator" and running == "feature_skip"):
            status = "running"
        else:
            status = "pending"
        steps.append({"node": node, "label": _STEP_LABELS[node], "status": status})
    total = len(steps)
    step = next((i + 1 for i, row in enumerate(steps) if row["status"] != "done"), total)
    return {"steps": steps, "step": step, "total": total}


def plan_view(state: dict, *, versions: dict[str, int] | None = None, running: str = "") -> dict:
    """The whole plan as plain data. ``versions`` is ``{section: accepted count}``."""
    counts = versions or {}
    sections = [
        {
            "kind": kind,
            "title": SECTION_TITLES[kind],
            "status": section_status(state, kind, running=running),
            "version": int(counts.get(kind, 0)),
            "versions": int(counts.get(kind, 0)),
        }
        for kind in SECTION_KINDS
    ]
    view = {
        "stage": stage_of(state),
        "intake_mode": state.get("_intake_mode", ""),
        "sections": sections,
        "intake": _intake(state),
        "analysis": _analysis(state),
        "epic": _epic(state),
        "features": [_plain(item) for item in state.get("features") or []],
        "stories": [_story(item) for item in state.get("stories") or []],
        "tasks": [_plain(item) for item in state.get("tasks") or []],
        "sprints": [_plain(item) for item in state.get("sprints") or []],
        "capacity": _capacity(state),
        "sync": {key: _plain(state[key]) for key in _SYNC_KEYS if state.get(key)},
        "counts": {kind: len(state.get(kind) or []) for kind in ("features", "stories", "tasks", "sprints")},
    }
    logger.debug("plan_view: stage=%s statuses=%s", view["stage"], [s["status"] for s in sections])
    return view


def intake_source(number: int, qs) -> str:
    """The terminal's provenance tag for one answer, "" before the run reaches it."""
    if number in qs.extracted_questions:
        return "from description"
    if number in qs.defaulted_questions:
        return "default"
    if number in qs.answers:
        return "answered"
    if number in qs.skipped_questions:
        return "skipped"
    return ""


def _intake(state: dict) -> dict:
    from yeaboi.agent.state import PHASE_QUESTION_RANGES
    from yeaboi.prompts.intake import PHASE_LABELS, QUESTION_SHORT_LABELS

    qs = questionnaire(state)
    prior_art = [
        {"key": ref.key, "name": ref.name, "url": ref.url, "platform": ref.platform}
        for ref in state.get("prior_art") or ()
    ]
    if qs is None:
        return {
            "completed": False,
            "confirmed": False,
            "prior_art_pending": False,
            "phases": [],
            "prior_art": prior_art,
        }
    phases = []
    for phase, (start, end) in PHASE_QUESTION_RANGES.items():
        key = str(phase.value)
        questions = [
            {
                "number": number,
                "label": QUESTION_SHORT_LABELS.get(number, f"Question {number}"),
                "answer": qs.answers.get(number, ""),
                "source": intake_source(number, qs),
                "origin": str(qs.answer_sources.get(number, "")),
                "skipped": number in qs.skipped_questions,
            }
            for number in range(start, end + 1)
        ]
        phases.append({"key": key, "label": _PHASE_PREFIX.sub("", PHASE_LABELS.get(key, key)), "questions": questions})
    return {
        "completed": bool(qs.completed),
        "confirmed": bool(qs.completed and not qs.awaiting_confirmation),
        "prior_art_pending": getattr(qs, "_prior_art_stage", "") in ("ask", "reason", "empty"),
        "phases": phases,
        "prior_art": prior_art,
    }


def _analysis(state: dict) -> dict:
    analysis = state.get("project_analysis")
    if not is_dataclass(analysis):
        return {}
    qs = questionnaire(state)
    architecture = analysis.architecture
    return {
        "name": analysis.project_name,
        "description": analysis.project_description,
        "type": analysis.project_type,
        "goals": list(analysis.goals),
        "end_users": list(analysis.end_users),
        "target_state": analysis.target_state,
        "tech_stack": list(analysis.tech_stack),
        "integrations": list(analysis.integrations),
        "constraints": list(analysis.constraints),
        "sprint_length_weeks": analysis.sprint_length_weeks,
        "target_sprints": analysis.target_sprints,
        "risks": list(analysis.risks),
        "out_of_scope": list(analysis.out_of_scope),
        "assumptions": list(analysis.assumptions),
        "skip_features": bool(analysis.skip_features),
        "is_low_code": bool(analysis.is_low_code),
        "low_code_reason": analysis.low_code_reason,
        "architecture": _plain(architecture) if architecture is not None and architecture.options else {},
        "team_size": (qs.answers.get(6, "") if qs is not None else ""),
    }


def _epic(state: dict) -> dict:
    analysis = state.get("project_analysis")
    if not is_dataclass(analysis):
        return {}
    return {
        "reviewed": bool(state.get("_epic_reviewed")),
        "calibration_profile_id": state.get("analysis_profile_id", "") or "",
        "name": analysis.project_name,
        "description": analysis.project_description,
        "goals": list(analysis.goals),
    }


def _capacity(state: dict) -> dict:
    return {
        "velocity_per_sprint": state.get("velocity_per_sprint", 0) or 0,
        "net_velocity_per_sprint": state.get("net_velocity_per_sprint", 0) or 0,
        "velocity_source": state.get("velocity_source", "") or "",
        "sprint_start_date": state.get("sprint_start_date", "") or "",
        "sprint_length_weeks": state.get("sprint_length_weeks", 0) or 0,
        "target_sprints": state.get("target_sprints", 0) or 0,
    }


def _story(story) -> dict:
    data = _plain(story)
    if isinstance(data, dict) and "story_points" in data:
        try:
            data["story_points"] = int(data["story_points"])
        except (TypeError, ValueError):
            pass
    return data


def _plain(value):
    """Dataclasses, enums, tuples and sets as the JSON types a drawer reads."""
    if is_dataclass(value) and not isinstance(value, type):
        return _plain(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(v) for v in value]
    return value
