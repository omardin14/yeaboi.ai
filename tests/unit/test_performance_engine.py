"""Unit tests for the Performance engine pipelines (mocked LLM + activity)."""

import json
from datetime import date

import pytest

from scrum_agent.agent.state import EngineerActivity, EngineerStory
from scrum_agent.performance import engine
from scrum_agent.performance.store import PerformanceStore


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "sessions.db"


class _FakeResp:
    def __init__(self, content):
        self.content = content
        self.response_metadata = {}


def _patch_llm(monkeypatch, content):
    """Make the engine's single LLM call return ``content`` and report configured."""
    monkeypatch.setattr("scrum_agent.config.is_llm_configured", lambda: (True, ""))
    monkeypatch.setattr("scrum_agent.agent.llm.track_usage", lambda resp: None)
    monkeypatch.setattr(
        "scrum_agent.agent.llm.get_llm",
        lambda **k: type("L", (), {"invoke": lambda self, m: _FakeResp(content)})(),
    )


def _patch_activity(monkeypatch, stories=()):
    monkeypatch.setattr(
        engine.activity_mod,
        "gather_engineer_activity",
        lambda engineer, **kw: EngineerActivity(
            engineer=engineer, current_sprint="Sprint 5", stories=tuple(stories), total_items=len(stories)
        ),
    )


@pytest.fixture(autouse=True)
def _no_export(monkeypatch):
    # Keep tests off the real ~/.scrum-agent export dir.
    monkeypatch.setattr("scrum_agent.performance.export.export_artifact", lambda *a, **k: {})


class TestOneOnOnePrep:
    def test_happy_path_parses_llm(self, monkeypatch, db_path):
        _patch_activity(monkeypatch, stories=[EngineerStory(key="P-1", title="auth")])
        _patch_llm(
            monkeypatch,
            json.dumps(
                {
                    "talking_points": ["Discuss auth"],
                    "feedback": ["Great ownership"],
                    "goals": ["Ship v2"],
                    "gaps": [],
                    "improvements": ["Write more tests"],
                    "activity_summary": "Worked on auth.",
                }
            ),
        )
        prep = engine.run_one_on_one_prep("Ada", db_path=db_path, today=date(2026, 7, 12))
        assert prep.talking_points == ("Discuss auth",)
        assert prep.feedback == ("Great ownership",)
        assert prep.activity_summary == "Worked on auth."
        # Persisted.
        with PerformanceStore(db_path) as store:
            assert store.get_latest_prep("Ada") is not None

    def test_carried_actions_always_surface(self, monkeypatch, db_path):
        _patch_activity(monkeypatch)
        # Seed a prior completion with an open action.
        from scrum_agent.agent.state import OneOnOneRecord

        with PerformanceStore(db_path) as store:
            store.record_completion(
                OneOnOneRecord(engineer="Ada", date="2026-07-01", action_items=("finish migration",))
            )
        # LLM drops the carried action — engine must re-add it.
        _patch_llm(monkeypatch, json.dumps({"talking_points": ["something else"]}))
        prep = engine.run_one_on_one_prep("Ada", db_path=db_path, today=date(2026, 7, 12))
        assert "finish migration" in prep.talking_points
        assert prep.carried_action_items == ("finish migration",)

    def test_llm_not_configured_falls_back(self, monkeypatch, db_path):
        _patch_activity(monkeypatch, stories=[EngineerStory(key="P-1", title="auth")])
        monkeypatch.setattr("scrum_agent.config.is_llm_configured", lambda: (False, "no key"))
        prep = engine.run_one_on_one_prep("Ada", db_path=db_path, today=date(2026, 7, 12))
        assert prep.warnings and "no key" in prep.warnings[0]
        assert prep.talking_points  # deterministic points present

    def test_code_fence_response_parses(self, monkeypatch, db_path):
        _patch_activity(monkeypatch)
        fenced = "```json\n" + json.dumps({"talking_points": ["x"]}) + "\n```"
        _patch_llm(monkeypatch, fenced)
        prep = engine.run_one_on_one_prep("Ada", db_path=db_path, today=date(2026, 7, 12))
        assert prep.talking_points == ("x",)


class TestCompletion:
    def test_happy_path_and_action_items_persist(self, monkeypatch, db_path):
        _patch_llm(
            monkeypatch,
            json.dumps(
                {
                    "email_subject": "1:1 follow-up",
                    "email_summary": "Hi Ada, great chat.",
                    "action_items": ["Book design review"],
                    "highlights": ["Discussed growth"],
                }
            ),
        )
        record = engine.complete_one_on_one("Ada", "we talked", db_path=db_path, deliver=False, today=date(2026, 7, 12))
        assert record.action_items == ("Book design review",)
        # Flows into the next prep's carried actions.
        with PerformanceStore(db_path) as store:
            assert store.get_open_action_items("Ada") == ("Book design review",)

    def test_empty_transcript_short_circuits(self, monkeypatch, db_path):
        record = engine.complete_one_on_one("Ada", "   ", db_path=db_path, deliver=False)
        assert "No transcript" in record.warnings[0]

    def test_llm_failure_keeps_transcript(self, monkeypatch, db_path):
        monkeypatch.setattr("scrum_agent.config.is_llm_configured", lambda: (True, ""))
        monkeypatch.setattr("scrum_agent.agent.llm.track_usage", lambda resp: None)

        def boom(self, m):
            raise RuntimeError("timeout")

        monkeypatch.setattr("scrum_agent.agent.llm.get_llm", lambda **k: type("L", (), {"invoke": boom})())
        record = engine.complete_one_on_one(
            "Ada", "notes here", db_path=db_path, deliver=False, today=date(2026, 7, 12)
        )
        assert record.transcript == "notes here"
        assert record.warnings


class TestReview:
    def test_happy_path_parses(self, monkeypatch, db_path):
        _patch_activity(monkeypatch, stories=[EngineerStory(key="P-1", title="auth", status="Done")])
        _patch_llm(
            monkeypatch,
            json.dumps(
                {
                    "strengths": ["Technical depth"],
                    "areas_for_improvement": ["Delegation"],
                    "achievements": ["Shipped auth"],
                    "goals": ["Lead a project"],
                    "overall": "Strong contributor.",
                }
            ),
        )
        review = engine.run_six_month_review("Ada", db_path=db_path, today=date(2026, 7, 12))
        assert review.strengths == ("Technical depth",)
        assert review.overall == "Strong contributor."
        assert review.framework_used == "default"
        assert review.period_start and review.period_end

    def test_llm_unavailable_falls_back(self, monkeypatch, db_path):
        _patch_activity(monkeypatch)
        monkeypatch.setattr("scrum_agent.config.is_llm_configured", lambda: (False, "no key"))
        review = engine.run_six_month_review("Ada", db_path=db_path, today=date(2026, 7, 12))
        assert review.warnings
        assert review.framework_used == "default"
