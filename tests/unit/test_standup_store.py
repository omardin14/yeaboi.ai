"""Unit tests for the Daily Standup SQLite store."""

import pytest

from yeaboi.agent.state import MemberUpdate, StandupReport
from yeaboi.standup.store import StandupStore


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "sessions.db"


def _make_report(**overrides) -> StandupReport:
    base = dict(
        date="2026-07-10",
        session_id="s1",
        sprint_name="Sprint 5",
        sprint_day=3,
        sprint_total_days=10,
        confidence_pct=82,
        confidence_label="At risk",
        member_updates=(MemberUpdate(name="Alice", summary="login"),),
        activity_counts=(("jira", 4),),
    )
    base.update(overrides)
    return StandupReport(**base)


class TestConfig:
    def test_save_and_load(self, db_path):
        with StandupStore(db_path) as store:
            store.save_config(
                "s1",
                enabled=True,
                time="10:00",
                lead_minutes=15,
                weekdays="1-5",
                delivery_channels=["terminal", "slack"],
                repo_path="/tmp/repo",
            )
            cfg = store.load_config("s1")
        assert cfg is not None
        assert cfg["enabled"] is True
        assert cfg["time"] == "10:00"
        assert cfg["lead_minutes"] == 15
        assert cfg["delivery_channels"] == ["terminal", "slack"]
        assert cfg["repo_path"] == "/tmp/repo"

    def test_lead_minutes_defaults_to_10(self, db_path):
        with StandupStore(db_path) as store:
            store.save_config("s1", enabled=True, time="10:00", weekdays="1-5", delivery_channels=["terminal"])
            cfg = store.load_config("s1")
        assert cfg["lead_minutes"] == 10

    def test_load_missing_returns_none(self, db_path):
        with StandupStore(db_path) as store:
            assert store.load_config("nope") is None

    def test_upsert_updates_existing(self, db_path):
        with StandupStore(db_path) as store:
            store.save_config("s1", enabled=True, time="09:50", weekdays="1-5", delivery_channels=["terminal"])
            store.save_config("s1", enabled=False, time="10:00", weekdays="1-5", delivery_channels=["email"])
            cfg = store.load_config("s1")
        assert cfg["enabled"] is False
        assert cfg["time"] == "10:00"
        assert cfg["delivery_channels"] == ["email"]

    def test_corrupt_channels_falls_back(self, db_path):
        with StandupStore(db_path) as store:
            store.save_config("s1", enabled=True, time="09:50", weekdays="1-5", delivery_channels=["terminal"])
            store._conn.execute("UPDATE standup_config SET delivery_channels = 'not json' WHERE session_id='s1'")
            cfg = store.load_config("s1")
        assert cfg["delivery_channels"] == ["terminal"]


class TestSelfUpdates:
    def test_save_and_get(self, db_path):
        with StandupStore(db_path) as store:
            store.save_my_update("s1", "2026-07-10", "Alice", "shipped the login page")
            updates = store.get_my_updates("s1", "2026-07-10")
        assert updates == {"Alice": "shipped the login page"}

    def test_resubmit_overwrites(self, db_path):
        with StandupStore(db_path) as store:
            store.save_my_update("s1", "2026-07-10", "Alice", "first")
            store.save_my_update("s1", "2026-07-10", "Alice", "second")
            updates = store.get_my_updates("s1", "2026-07-10")
        assert updates == {"Alice": "second"}

    def test_scoped_by_date(self, db_path):
        with StandupStore(db_path) as store:
            store.save_my_update("s1", "2026-07-10", "Alice", "today")
            assert store.get_my_updates("s1", "2026-07-11") == {}


class TestRunHistory:
    def test_record_and_get_latest(self, db_path):
        report = _make_report()
        with StandupStore(db_path) as store:
            row_id = store.record_run(report, delivery_status={"terminal": True}, status="success")
            latest = store.get_latest_report("s1")
        assert row_id > 0
        assert latest == report

    def test_get_latest_missing_returns_none(self, db_path):
        with StandupStore(db_path) as store:
            assert store.get_latest_report("s1") is None

    def test_latest_is_most_recent(self, db_path):
        with StandupStore(db_path) as store:
            store.record_run(_make_report(date="2026-07-09", confidence_pct=50))
            store.record_run(_make_report(date="2026-07-10", confidence_pct=90))
            latest = store.get_latest_report("s1")
        assert latest.date == "2026-07-10"
        assert latest.confidence_pct == 90

    def test_get_history(self, db_path):
        with StandupStore(db_path) as store:
            store.record_run(_make_report(date="2026-07-09"))
            store.record_run(_make_report(date="2026-07-10"))
            history = store.get_history("s1")
        assert len(history) == 2
        assert history[0]["standup_date"] == "2026-07-10"  # newest first
        assert history[0]["confidence_pct"] == 82

    def test_corrupt_report_json_returns_none(self, db_path):
        with StandupStore(db_path) as store:
            store.record_run(_make_report())
            store._conn.execute("UPDATE standup_history SET report_json = 'garbage'")
            assert store.get_latest_report("s1") is None


class TestMigrationCreatesTables:
    def test_session_store_v6_creates_standup_tables(self, db_path):
        """Opening a SessionStore should run the v6 migration and create standup tables."""
        from yeaboi.sessions import CURRENT_SCHEMA_VERSION, SessionStore

        assert CURRENT_SCHEMA_VERSION >= 6
        with SessionStore(db_path):
            pass
        # A fresh StandupStore on the same DB should find existing tables and work.
        with StandupStore(db_path) as store:
            store.save_config("s1", enabled=True, time="09:50", weekdays="1-5", delivery_channels=["terminal"])
            assert store.load_config("s1") is not None
