"""Unit tests for the standup engine pipeline (mocked LLM + sources)."""

import json
from datetime import date

import pytest

from yeaboi.sessions import SessionStore
from yeaboi.standup import engine
from yeaboi.standup.collector import ActivityBundle
from yeaboi.standup.sprint_context import SprintContext
from yeaboi.standup.store import StandupStore


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "sessions.db"


@pytest.fixture
def seeded_session(db_path):
    """Create a session with a plan and return its id."""
    sid = "sess-1"
    with SessionStore(db_path) as s:
        s.create_session(sid, "Demo Project", mode="planning")
        s.save_state(sid, {"selected_team_members": ("Alice", "Bob"), "sprint_length_weeks": 2})
    return sid


class _FakeResp:
    def __init__(self, content):
        self.content = content
        self.response_metadata = {}


def _patch_common(monkeypatch, *, items, counts):
    """Patch collector, sprint_context, and token tracking for engine tests."""
    monkeypatch.setattr(
        engine.collector,
        "collect_recent_activity",
        lambda **kw: ActivityBundle(items=items, counts=counts),
    )
    monkeypatch.setattr(
        engine.sprint_context,
        "gather",
        lambda state, **kw: SprintContext(
            sprint_name="Sprint 5",
            start_date="2026-07-06",
            sprint_length_weeks=2,
            capacity_points=20,
            completed_points=10,
            have_burn=True,
        ),
    )
    monkeypatch.setattr("yeaboi.agent.llm.track_usage", lambda resp: None)
    # Pretend the LLM provider is configured so the summarizer exercises the LLM
    # branch (individual tests override this to test the not-configured path).
    monkeypatch.setattr("yeaboi.config.is_llm_configured", lambda: (True, ""))


class TestRunStandup:
    def test_happy_path_with_llm(self, monkeypatch, db_path, seeded_session):
        items = [
            {"author": "Alice", "kind": "commit", "title": "login page", "source": "github"},
            {"author": "Bob", "kind": "issue", "title": "API bug", "source": "jira"},
        ]
        _patch_common(monkeypatch, items=items, counts=[("github", 1), ("jira", 1)])
        llm_json = json.dumps(
            {
                "members": [
                    {"name": "Alice", "summary": "Built the login page", "blockers": ""},
                    {"name": "Bob", "summary": "Fixed an API bug", "blockers": "waiting on review"},
                ],
                "team_summary": "Solid progress across the board.",
            }
        )
        monkeypatch.setattr(
            "yeaboi.agent.llm.get_llm",
            lambda **k: type("L", (), {"invoke": lambda self, m: _FakeResp(llm_json)})(),
        )

        report = engine.run_standup(seeded_session, deliver=False, db_path=db_path, today=date(2026, 7, 10))

        assert report.sprint_day == 5
        assert report.confidence_pct == 100
        assert report.confidence_label == "On track"
        assert report.team_summary == "Solid progress across the board."
        names = {m.name: m for m in report.member_updates}
        assert names["Bob"].blockers == "waiting on review"
        assert all(m.source == "inferred" for m in report.member_updates)
        assert report.activity_counts == (("github", 1), ("jira", 1))

    def test_self_reported_is_verbatim(self, monkeypatch, db_path, seeded_session):
        _patch_common(
            monkeypatch,
            items=[{"author": "Bob", "kind": "issue", "title": "x", "source": "jira"}],
            counts=[("jira", 1)],
        )
        with StandupStore(db_path) as store:
            store.save_my_update(seeded_session, "2026-07-10", "Alice", "I paired with Bob on auth all day.")
        llm_json = json.dumps({"members": [{"name": "Bob", "summary": "Worked on x"}], "team_summary": "ok"})
        monkeypatch.setattr(
            "yeaboi.agent.llm.get_llm",
            lambda **k: type("L", (), {"invoke": lambda self, m: _FakeResp(llm_json)})(),
        )

        report = engine.run_standup(seeded_session, deliver=False, db_path=db_path, today=date(2026, 7, 10))
        alice = next(m for m in report.member_updates if m.name == "Alice")
        assert alice.source == "self-reported"
        assert alice.summary == "I paired with Bob on auth all day."

    def test_llm_failure_falls_back(self, monkeypatch, db_path, seeded_session):
        _patch_common(
            monkeypatch,
            items=[{"author": "Alice", "kind": "commit", "title": "did work", "source": "github"}],
            counts=[("github", 1)],
        )

        def boom(self, m):
            raise RuntimeError("timeout")

        monkeypatch.setattr("yeaboi.agent.llm.get_llm", lambda **k: type("L", (), {"invoke": boom})())
        report = engine.run_standup(seeded_session, deliver=False, db_path=db_path, today=date(2026, 7, 10))
        # Fallback: Alice's summary is her activity title.
        alice = next(m for m in report.member_updates if m.name == "Alice")
        assert "did work" in alice.summary
        assert report.team_summary  # deterministic team summary present

    def test_auth_error_becomes_warning(self, monkeypatch, db_path, seeded_session):
        _patch_common(
            monkeypatch,
            items=[{"author": "Alice", "kind": "commit", "title": "x", "source": "github"}],
            counts=[("github", 1)],
        )

        import anthropic

        def boom(self, m):
            raise anthropic.AuthenticationError.__new__(anthropic.AuthenticationError)

        monkeypatch.setattr("yeaboi.agent.llm.get_llm", lambda **k: type("L", (), {"invoke": boom})())
        # No longer raises — surfaces a warning and falls back deterministically.
        report = engine.run_standup(seeded_session, deliver=False, db_path=db_path, today=date(2026, 7, 10))
        assert any("API key invalid" in w for w in report.warnings)
        alice = next(m for m in report.member_updates if m.name == "Alice")
        assert "x" in alice.summary  # deterministic fallback used

    def test_no_api_key_warns(self, monkeypatch, db_path, seeded_session):
        _patch_common(
            monkeypatch,
            items=[{"author": "Alice", "kind": "commit", "title": "shipped x", "source": "github"}],
            counts=[("github", 1)],
        )
        monkeypatch.setattr("yeaboi.config.is_llm_configured", lambda: (False, "ANTHROPIC_API_KEY not set"))

        # get_llm should never be called when the provider isn't configured.
        def _should_not_call(**k):
            raise AssertionError("LLM must not be invoked when unconfigured")

        monkeypatch.setattr("yeaboi.agent.llm.get_llm", _should_not_call)
        report = engine.run_standup(seeded_session, deliver=False, db_path=db_path, today=date(2026, 7, 10))
        assert any("ANTHROPIC_API_KEY not set" in w for w in report.warnings)

    def test_source_auth_error_surfaces_as_warning(self, monkeypatch, db_path, seeded_session):
        # Collector reports a source auth error → it appears in report.warnings.
        from yeaboi.standup.collector import ActivityBundle

        monkeypatch.setattr(
            engine.collector,
            "collect_recent_activity",
            lambda **kw: ActivityBundle(items=[], counts=[], errors=[("jira", "authentication failed — check token")]),
        )
        monkeypatch.setattr(
            engine.sprint_context,
            "gather",
            lambda state, **kw: __import__("yeaboi.standup.sprint_context", fromlist=["SprintContext"]).SprintContext(),
        )
        monkeypatch.setattr("yeaboi.agent.llm.track_usage", lambda resp: None)
        monkeypatch.setattr("yeaboi.config.is_llm_configured", lambda: (True, ""))
        llm_json = json.dumps(
            {"members": [{"name": "Alice", "summary": "x"}, {"name": "Bob", "summary": "y"}], "team_summary": "ok"}
        )
        monkeypatch.setattr(
            "yeaboi.agent.llm.get_llm",
            lambda **k: type("L", (), {"invoke": lambda self, m: _FakeResp(llm_json)})(),
        )
        report = engine.run_standup(seeded_session, deliver=False, db_path=db_path, today=date(2026, 7, 10))
        assert any("Jira: authentication failed" in w for w in report.warnings)

    def test_auto_exports_md_and_html(self, monkeypatch, db_path, seeded_session, tmp_path):
        _patch_common(monkeypatch, items=[], counts=[])
        monkeypatch.setattr("yeaboi.paths.STANDUP_EXPORTS_DIR", tmp_path / "exports" / "standup")
        llm_json = json.dumps(
            {"members": [{"name": "Alice", "summary": "x"}, {"name": "Bob", "summary": "y"}], "team_summary": "ok"}
        )
        monkeypatch.setattr(
            "yeaboi.agent.llm.get_llm",
            lambda **k: type("L", (), {"invoke": lambda self, m: _FakeResp(llm_json)})(),
        )
        engine.run_standup(seeded_session, deliver=False, db_path=db_path, today=date(2026, 7, 10))
        # A dated .md + .html were written under the standup exports dir.
        exports = list((tmp_path / "exports" / "standup").rglob("standup-2026-07-10.*"))
        assert {p.suffix for p in exports} == {".md", ".html"}

    def test_records_run_to_history(self, monkeypatch, db_path, seeded_session):
        _patch_common(monkeypatch, items=[], counts=[])
        # No members with activity and no self-reports besides roster → LLM still called for inferred roster.
        llm_json = json.dumps(
            {
                "members": [{"name": "Alice", "summary": "quiet day"}, {"name": "Bob", "summary": "quiet day"}],
                "team_summary": "quiet",
            }
        )
        monkeypatch.setattr(
            "yeaboi.agent.llm.get_llm",
            lambda **k: type("L", (), {"invoke": lambda self, m: _FakeResp(llm_json)})(),
        )

        engine.run_standup(seeded_session, deliver=False, db_path=db_path, today=date(2026, 7, 10))
        with StandupStore(db_path) as store:
            latest = store.get_latest_report(seeded_session)
            history = store.get_history(seeded_session)
        assert latest is not None
        assert len(history) == 1

    def test_delivery_invoked_when_enabled(self, monkeypatch, db_path, seeded_session):
        _patch_common(monkeypatch, items=[], counts=[])
        llm_json = json.dumps(
            {"members": [{"name": "Alice", "summary": "x"}, {"name": "Bob", "summary": "y"}], "team_summary": "ok"}
        )
        monkeypatch.setattr(
            "yeaboi.agent.llm.get_llm",
            lambda **k: type("L", (), {"invoke": lambda self, m: _FakeResp(llm_json)})(),
        )

        delivered = {}

        def fake_deliver(report, channels):
            delivered["channels"] = channels
            return {c: True for c in channels}

        import yeaboi.standup.delivery as delivery_mod

        monkeypatch.setattr(delivery_mod, "deliver", fake_deliver)
        engine.run_standup(
            seeded_session, deliver=True, channels=["terminal"], db_path=db_path, today=date(2026, 7, 10)
        )
        assert delivered["channels"] == ["terminal"]
