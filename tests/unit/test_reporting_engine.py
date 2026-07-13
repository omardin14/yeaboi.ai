"""Unit tests for the Reporting engine pipeline (mocked LLM + activity)."""

import json

import pytest

from scrum_agent.agent.state import DeliveredItem
from scrum_agent.reporting import activity as activity_mod
from scrum_agent.reporting import engine


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


def _patch_activity(monkeypatch, items=(), sprints=(), warnings=()):
    monkeypatch.setattr(
        activity_mod,
        "gather_delivered_work",
        lambda period, **kw: (list(items), list(sprints), list(warnings)),
    )


@pytest.fixture(autouse=True)
def _no_export(monkeypatch):
    # Keep tests off the real ~/.scrum-agent export dir.
    monkeypatch.setattr("scrum_agent.reporting.export.export_report", lambda *a, **k: {})


def _items(n=2):
    return [
        DeliveredItem(key=f"P-{i}", title=f"feature {i}", status="Done", source="jira", assignee="Ada")
        for i in range(n)
    ]


class TestRunDeliveryReport:
    def test_happy_path_parses_llm(self, monkeypatch, db_path):
        _patch_activity(monkeypatch, items=_items(3), sprints=["Sprint 5"])
        _patch_llm(
            monkeypatch,
            json.dumps(
                {
                    "headline": "Big wins this sprint.",
                    "executive_summary": "We shipped a lot.",
                    "themes": [{"title": "Security", "outcomes": ["SSO", "MFA"]}],
                    "highlights": ["SSO live"],
                    "emoji_theme": {"headline": "🔐", "highlights": "⭐"},
                }
            ),
        )
        report = engine.run_delivery_report("last_sprint", session_id="", db_path=db_path)
        assert report.headline == "Big wins this sprint."
        assert report.themes == (("Security", ("SSO", "MFA")),)
        assert report.highlights == ("SSO live",)
        assert ("Items delivered", "3") in report.metrics
        # emoji: LLM slot honoured, missing slots defaulted
        emoji = dict(report.emoji_theme)
        assert emoji["headline"] == "🔐"
        assert emoji["summary"]  # defaulted, not empty
        assert not report.warnings

    def test_llm_failure_falls_back(self, monkeypatch, db_path):
        _patch_activity(monkeypatch, items=_items(2))
        # is_llm_configured True but the call raises a generic error → fallback
        monkeypatch.setattr("scrum_agent.config.is_llm_configured", lambda: (True, ""))
        monkeypatch.setattr("scrum_agent.agent.llm.track_usage", lambda resp: None)

        def _boom(**k):
            raise RuntimeError("network down")

        monkeypatch.setattr("scrum_agent.agent.llm.get_llm", _boom)
        report = engine.run_delivery_report("last_month", session_id="", db_path=db_path)
        assert report.delivered_items  # evidence preserved
        assert report.themes  # deterministic "Delivered work" theme
        assert any("unavailable" in w.lower() for w in report.warnings)

    def test_auth_error_becomes_warning_not_raised(self, monkeypatch, db_path):
        _patch_activity(monkeypatch, items=_items(1))
        monkeypatch.setattr("scrum_agent.config.is_llm_configured", lambda: (True, ""))
        monkeypatch.setattr("scrum_agent.agent.llm.track_usage", lambda resp: None)
        monkeypatch.setattr("scrum_agent.agent.nodes._is_llm_auth_or_billing_error", lambda e: True)

        def _boom(**k):
            raise RuntimeError("401 invalid api key")

        monkeypatch.setattr("scrum_agent.agent.llm.get_llm", _boom)
        report = engine.run_delivery_report("last_sprint", db_path=db_path)  # must not raise
        assert any("billing" in w.lower() or "invalid" in w.lower() for w in report.warnings)

    def test_no_items_skips_llm(self, monkeypatch, db_path):
        _patch_activity(monkeypatch, items=[], warnings=["No board configured"])

        # If the LLM were called this would blow up (get_llm not patched to succeed).
        def _fail(**k):
            raise AssertionError("LLM must not be called when there is no delivered work")

        monkeypatch.setattr("scrum_agent.agent.llm.get_llm", _fail)
        monkeypatch.setattr("scrum_agent.config.is_llm_configured", lambda: (True, ""))
        report = engine.run_delivery_report("last_month", db_path=db_path)
        assert report.delivered_items == ()
        assert report.warnings == ("No board configured",)
        assert report.metrics == (("Items delivered", "0"),)

    def test_persists_to_store(self, monkeypatch, db_path):
        _patch_activity(monkeypatch, items=_items(2))
        _patch_llm(monkeypatch, "{}")  # empty parse → fallback, still persists
        engine.run_delivery_report("last_sprint", session_id="s1", db_path=db_path)
        from scrum_agent.reporting.store import ReportingStore

        with ReportingStore(db_path) as store:
            assert store.get_latest_report() is not None
            assert len(store.get_history()) == 1


class TestQuarterReport:
    def test_quarter_uses_window_and_labels(self, monkeypatch, db_path):
        captured = {}

        def _fake_gather(period, **kw):
            captured["period"] = period
            captured["days_override"] = kw.get("days_override")
            return list(_items(2)), [], []

        monkeypatch.setattr(activity_mod, "gather_delivered_work", _fake_gather)
        _patch_llm(monkeypatch, "{}")  # empty parse → fallback, keeps it deterministic

        from datetime import date

        report = engine.run_delivery_report(
            activity_mod.PERIOD_QUARTER,
            db_path=db_path,
            today=date(2026, 7, 13),
            window_start="2026-04-01",
            window_end="2026-06-30",
            sprint_names=("Sprint 8", "Sprint 9"),
            period_label_override="Q2 2026",
        )
        assert report.period_label == "Q2 2026"
        assert report.period_start == "2026-04-01"
        assert report.period_end == "2026-06-30"
        assert report.sprint_names == ("Sprint 8", "Sprint 9")
        assert captured["period"] == activity_mod.PERIOD_QUARTER
        # 2026-04-01 → 2026-07-13 is 103 days
        assert captured["days_override"] == 103
        assert any("truncated" in w.lower() for w in report.warnings)


class TestMetrics:
    def test_counts_sources_and_contributors(self):
        items = [
            DeliveredItem(key="J-1", status="Done", source="jira", assignee="Ada"),
            DeliveredItem(key="J-2", status="Done", source="jira", assignee="Bo"),
            DeliveredItem(key="#3", status="Closed", source="azuredevops", assignee="Ada"),
        ]
        metrics = dict(engine._compute_metrics(items))
        assert metrics["Items delivered"] == "3"
        assert metrics["Contributors"] == "2"
        assert metrics["From Jira"] == "2"
        assert metrics["From Azure DevOps"] == "1"


class TestPeriodDays:
    def test_last_sprint_is_one_sprint(self):
        assert activity_mod.period_days("last_sprint", sprint_length_weeks=2) == 14
        assert activity_mod.period_days("last_sprint", sprint_length_weeks=1) == 7

    def test_last_month_is_at_least_28(self):
        assert activity_mod.period_days("last_month", sprint_length_weeks=1) == 28
        assert activity_mod.period_days("last_month", sprint_length_weeks=2) == 28
        assert activity_mod.period_days("last_month", sprint_length_weeks=3) == 42
