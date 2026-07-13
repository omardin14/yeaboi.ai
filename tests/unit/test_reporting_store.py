"""Unit tests for reporting/store.ReportingStore + schema migration."""

import pytest

from scrum_agent.agent.state import DeliveredItem, DeliveryReport
from scrum_agent.reporting.store import ReportingStore, _dict_to_report, _report_to_json


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "sessions.db"


def _report():
    return DeliveryReport(
        period_label="Last sprint",
        period_start="2026-06-29",
        period_end="2026-07-13",
        project_name="Acme",
        sprint_names=("Sprint 12",),
        headline="Shipped.",
        executive_summary="Summary.",
        themes=(("Security", ("SSO", "MFA")),),
        highlights=("SSO live",),
        metrics=(("Items delivered", "7"),),
        delivered_items=(DeliveredItem(key="A-1", title="t", status="Done", source="jira", assignee="Ada"),),
        emoji_theme=(("headline", "🚀"),),
        warnings=("w",),
        generated_at="2026-07-13",
    )


class TestRoundTrip:
    def test_json_round_trip_preserves_tuples(self):
        import json

        original = _report()
        restored = _dict_to_report(json.loads(_report_to_json(original)))
        assert restored == original

    def test_missing_keys_default(self):
        restored = _dict_to_report({"period_label": "Last sprint"})
        assert restored.period_label == "Last sprint"
        assert restored.themes == ()
        assert restored.delivered_items == ()


class TestStore:
    def test_record_and_get_latest(self, db_path):
        with ReportingStore(db_path) as store:
            store.record_run(_report(), session_id="s1")
            latest = store.get_latest_report()
            assert latest is not None and latest.headline == "Shipped."
            assert store.get_latest_report("s1") is not None
            assert store.get_latest_report("nope") is None

    def test_history_metadata(self, db_path):
        with ReportingStore(db_path) as store:
            store.record_run(_report(), session_id="s1")
            hist = store.get_history()
            assert len(hist) == 1
            assert hist[0]["item_count"] == 1
            assert hist[0]["period"] == "Last sprint"


class TestSchemaMigration:
    def test_current_version_is_9(self):
        from scrum_agent.sessions import CURRENT_SCHEMA_VERSION

        assert CURRENT_SCHEMA_VERSION == 9

    def test_session_store_creates_reporting_table(self, db_path):
        import sqlite3

        from scrum_agent.sessions import SessionStore

        with SessionStore(db_path):
            pass  # opening runs migrations up to v9
        conn = sqlite3.connect(str(db_path))
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "reporting_history" in names
