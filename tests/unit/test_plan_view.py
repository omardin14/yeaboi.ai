"""Tests for src/yeaboi/agent/plan_view.py — the plan as plain data."""

from __future__ import annotations

import json

import pytest

from tests._node_helpers import make_dummy_analysis
from yeaboi.agent.chat_session import EPIC_REVIEW_NODE, SECTION_KINDS
from yeaboi.agent.plan_view import (
    INTAKE_SOURCES,
    SECTION_TITLES,
    STATUSES,
    intake_source,
    pipeline_progress,
    plan_view,
    section_status,
)
from yeaboi.agent.state import (
    AcceptanceCriterion,
    Feature,
    PriorArtRef,
    Priority,
    QuestionnaireState,
    Sprint,
    StoryPointValue,
    Task,
    UserStory,
)


def _qs(**kw) -> QuestionnaireState:
    qs = QuestionnaireState(intake_mode="smart", current_question=31)
    qs.answers = {1: "A booking app", 6: "4", 8: "20"}
    qs.answer_sources = {1: "direct", 6: "defaulted"}
    qs.extracted_questions = {1}
    qs.defaulted_questions = {6}
    qs.skipped_questions = {3}
    for key, value in kw.items():
        setattr(qs, key, value)
    return qs


def _story() -> UserStory:
    return UserStory(
        id="S1",
        feature_id="F1",
        persona="client",
        goal="book a slot",
        benefit="my time is held",
        acceptance_criteria=(AcceptanceCriterion(given="a slot", when="I book", then="it is mine"),),
        story_points=StoryPointValue.THREE,
        priority=Priority.HIGH,
    )


def _full_state() -> dict:
    return {
        "_intake_mode": "smart",
        "questionnaire": _qs(completed=True),
        "project_analysis": make_dummy_analysis(),
        "_epic_reviewed": True,
        "analysis_profile_id": "jira-PROJ-1",
        "features": [Feature(id="F1", title="Booking", description="Slots", priority=Priority.HIGH)],
        "stories": [_story()],
        "tasks": [Task(id="T1", story_id="S1", title="Model", description="Slot table")],
        "sprints": [Sprint(id="SP1", name="Sprint 1", goal="Book", capacity_points=20, story_ids=("S1",))],
        "prior_art": (PriorArtRef(key="acme/booking", name="booking", url="https://x", platform="github"),),
        "velocity_per_sprint": 20,
        "sprint_start_date": "2026-09-14",
        "sprint_length_weeks": 2,
        "jira_epic_key": "PROJ-1",
    }


class TestSectionStatus:
    def test_the_vocabulary_is_pinned(self):
        assert STATUSES == ("empty", "generating", "awaiting_review", "accepted")
        assert INTAKE_SOURCES == ("answered", "from description", "default", "skipped", "")
        assert tuple(SECTION_TITLES) == SECTION_KINDS

    def test_intake_moves_through_every_status(self):
        assert section_status({}, "intake") == "empty"
        assert section_status({"questionnaire": _qs(completed=False, current_question=4)}, "intake") == "generating"
        qs = _qs(completed=False, awaiting_confirmation=True)
        assert section_status({"questionnaire": qs}, "intake") == "awaiting_review"
        assert section_status({"questionnaire": _qs(completed=True)}, "intake") == "accepted"

    @pytest.mark.parametrize(
        ("kind", "node", "key"),
        [
            ("analysis", "project_analyzer", "project_analysis"),
            ("features", "feature_generator", "features"),
            ("stories", "story_writer", "stories"),
            ("tasks", "task_decomposer", "tasks"),
            ("sprints", "sprint_planner", "sprints"),
        ],
    )
    def test_an_artifact_section_moves_through_every_status(self, kind, node, key):
        assert section_status({}, kind) == "empty"
        assert section_status({}, kind, running=node) == "generating"
        assert section_status({key: [1], "pending_review": node}, kind) == "awaiting_review"
        assert section_status({key: [1]}, kind) == "accepted"

    def test_feature_skip_counts_as_the_feature_step(self):
        assert section_status({}, "features", running="feature_skip") == "generating"
        assert section_status({"features": [1], "pending_review": "feature_skip"}, "features") == "awaiting_review"

    def test_the_epic_needs_an_analysis_first(self):
        assert section_status({}, "epic") == "empty"
        with_analysis = {"project_analysis": make_dummy_analysis()}
        assert section_status(with_analysis, "epic") == "empty"
        assert section_status(with_analysis, "epic", running=EPIC_REVIEW_NODE) == "generating"
        assert section_status({**with_analysis, "pending_review": EPIC_REVIEW_NODE}, "epic") == "awaiting_review"
        assert section_status({**with_analysis, "_epic_reviewed": True}, "epic") == "accepted"

    def test_an_unknown_section_is_refused(self):
        with pytest.raises(ValueError, match="unknown plan section"):
            section_status({}, "budget")


class TestPipelineProgress:
    def test_an_empty_plan_is_at_step_one(self):
        progress = pipeline_progress({})
        assert progress["step"] == 1 and progress["total"] == 6
        assert [row["status"] for row in progress["steps"]] == ["pending"] * 6

    def test_done_steps_move_the_pointer(self):
        progress = pipeline_progress({"project_analysis": make_dummy_analysis(), "_epic_reviewed": True})
        assert [row["status"] for row in progress["steps"][:3]] == ["done", "done", "pending"]
        assert progress["step"] == 3

    def test_a_running_step_is_named(self):
        progress = pipeline_progress({"project_analysis": make_dummy_analysis()}, running="feature_skip")
        assert progress["steps"][2] == {
            "node": "feature_generator",
            "label": "Generating features",
            "status": "running",
        }

    def test_a_finished_build_points_past_the_last_step(self):
        state = _full_state()
        progress = pipeline_progress(state)
        assert progress["step"] == progress["total"] == 6


class TestIntakeSource:
    def test_the_four_tags_and_the_blank(self):
        qs = _qs()
        assert intake_source(1, qs) == "from description"
        assert intake_source(6, qs) == "default"
        assert intake_source(8, qs) == "answered"
        assert intake_source(3, qs) == "skipped"
        assert intake_source(20, qs) == ""


class TestPlanView:
    def test_it_is_json_and_text_and_numbers_only(self):
        view = plan_view(_full_state(), versions={"stories": 2})
        text = json.dumps(view)
        assert "<" not in text and "Priority." not in text

    def test_sections_carry_status_and_versions_in_order(self):
        view = plan_view(_full_state(), versions={"stories": 2})
        assert [s["kind"] for s in view["sections"]] == list(SECTION_KINDS)
        by_kind = {s["kind"]: s for s in view["sections"]}
        assert by_kind["stories"] == {
            "kind": "stories",
            "title": "Stories",
            "status": "accepted",
            "version": 2,
            "versions": 2,
        }
        assert by_kind["intake"]["status"] == "accepted" and by_kind["intake"]["version"] == 0

    def test_intake_groups_every_phase_with_sources(self):
        view = plan_view(_full_state())
        intake = view["intake"]
        assert intake["completed"] is True and intake["confirmed"] is True and intake["prior_art_pending"] is False
        assert [p["label"] for p in intake["phases"]][:2] == ["Project Context", "Team & Capacity"]
        first = intake["phases"][0]["questions"][0]
        assert first == {
            "number": 1,
            "label": first["label"],
            "answer": "A booking app",
            "source": "from description",
            "origin": "direct",
            "skipped": False,
        }
        assert intake["phases"][0]["questions"][2]["skipped"] is True
        assert intake["prior_art"] == [
            {"key": "acme/booking", "name": "booking", "url": "https://x", "platform": "github"}
        ]

    def test_an_empty_state_is_all_empty(self):
        view = plan_view({})
        assert {s["status"] for s in view["sections"]} == {"empty"}
        assert view["intake"]["phases"] == [] and view["analysis"] == {} and view["epic"] == {}
        assert view["features"] == [] and view["counts"] == {"features": 0, "stories": 0, "tasks": 0, "sprints": 0}

    def test_artifacts_are_plain(self):
        view = plan_view(_full_state())
        assert view["features"][0]["priority"] == "high"
        story = view["stories"][0]
        assert story["story_points"] == 3 and story["acceptance_criteria"][0]["given"] == "a slot"
        assert view["sprints"][0]["story_ids"] == ["S1"]
        assert view["counts"] == {"features": 1, "stories": 1, "tasks": 1, "sprints": 1}

    def test_analysis_epic_capacity_and_sync(self):
        view = plan_view(_full_state())
        assert view["analysis"]["name"] == make_dummy_analysis().project_name
        assert view["analysis"]["team_size"] == "4"
        assert view["epic"]["reviewed"] is True and view["epic"]["calibration_profile_id"] == "jira-PROJ-1"
        assert view["capacity"]["sprint_start_date"] == "2026-09-14" and view["capacity"]["velocity_per_sprint"] == 20
        assert view["sync"] == {"jira_epic_key": "PROJ-1"}
        assert view["stage"] == "chat" and view["intake_mode"] == "smart"
