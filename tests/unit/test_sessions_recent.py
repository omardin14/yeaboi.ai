"""Tests for src/yeaboi/sessions_recent.py — the cross-mode recent list."""

from __future__ import annotations

import sqlite3
from dataclasses import fields

import pytest

from yeaboi.agent.state import DeliveryReport, RetroReport, ShipRun, StandupReport, WeeklyReview
from yeaboi.sessions_recent import MODES, RecentSession, recent_sessions


@pytest.fixture
def db(tmp_path):
    return tmp_path / "sessions.db"


@pytest.fixture
def seeded(db):
    """One run per mode; the retro belongs to a different session."""
    from dataclasses import dataclass, field

    from yeaboi.agent.state import OneOnOnePrep, PokerReport, RoadmapAnalysis
    from yeaboi.agentwatch.store import AgentWatchStore
    from yeaboi.performance.store import PerformanceStore
    from yeaboi.poker.store import PokerStore
    from yeaboi.reporting.store import ReportingStore
    from yeaboi.retro.store import RetroStore
    from yeaboi.roadmap.ingest import RoadmapSource
    from yeaboi.roadmap.store import RoadmapStore
    from yeaboi.sessions import SessionStore
    from yeaboi.ship.store import ShipStore
    from yeaboi.solo.store import WeeklyReviewStore
    from yeaboi.standup.store import StandupStore

    @dataclass
    class _Report:
        period_start: str = "2026-08-01"
        warnings: tuple = field(default_factory=tuple)

    with SessionStore(db) as store:
        store.create_session("p1", "Apollo")
        store.create_session("a1", "Apollo", mode="analysis")
    with StandupStore(db) as store:
        store.record_run(StandupReport(session_id="p1", date="2026-09-01"))
    with RetroStore(db) as store:
        store.record_run(RetroReport(session_id="other", date="2026-08-30"))
    with ReportingStore(db) as store:
        store.record_run(DeliveryReport(period_label="Last week"), session_id="p1")
    with ShipStore(db) as store:
        store.record_run(ShipRun(run_id="r1", item_id="S-1", session_id="p1"))
    with WeeklyReviewStore(db) as store:
        store.record_run(WeeklyReview(session_id="p1", week_label="2026-W35"))
    with PokerStore(db) as store:
        store.record_run(PokerReport(date="2026-09-02", session_id="p1", source="jira", scope_label="Sprint 42"))
    with PerformanceStore(db) as store:
        store.record_prep(OneOnOnePrep(engineer="Ada", date="2026-09-03"))
    with RoadmapStore(db) as store:
        store.save_roadmap(
            RoadmapSource(source_type="local", locator="/tmp/q3.md", label="q3.md"),
            RoadmapAnalysis(source_type="local", source_locator="/tmp/q3.md", source_label="q3.md"),
        )
    with AgentWatchStore(db) as store:
        for kind in ("usage", "advisor", "security"):
            store.record_report(kind, _Report(), key_date="2026-08-08")
    return {"db": db}


class TestUnion:
    def test_every_store_contributes(self, seeded):
        rows = recent_sessions(db_path=seeded["db"])
        assert {r.mode for r in rows} == set(MODES)
        assert all(isinstance(r, RecentSession) for r in rows)

    def test_row_shape_is_pinned(self):
        assert [f.name for f in fields(RecentSession)] == [
            "session_id",
            "run_id",
            "mode",
            "title",
            "created_at",
            "last_modified",
            "subtitle",
            "kind",
            "project_label",
            "tags",
            "engineer",
        ]

    def test_titles_and_run_ids(self, seeded):
        by_mode = {r.mode: r for r in recent_sessions(db_path=seeded["db"])}
        assert by_mode["standup"].title == "Standup — 2026-09-01" and by_mode["standup"].run_id == "1"
        assert by_mode["retro"].title == "Retro — 2026-08-30"
        assert by_mode["reporting"].title == "Report — Last week"
        assert by_mode["ship"].title.startswith("Ship — S-1") and by_mode["ship"].run_id == "r1"
        assert by_mode["review"].title == "Week 2026-W35"
        assert by_mode["planning"].title.startswith("apollo-") and by_mode["planning"].run_id == ""
        assert by_mode["analysis"].session_id == "a1"
        assert by_mode["poker"].title == "Poker — 2026-09-02" and by_mode["poker"].subtitle.startswith("Sprint 42")
        assert by_mode["performance"].run_id == "prep:1" and by_mode["performance"].engineer == "Ada"
        assert by_mode["performance"].kind == "prep"
        assert by_mode["roadmap"].title == "Q3" and by_mode["roadmap"].run_id == "1"
        assert by_mode["agent-usage"].title == "Agent usage — 2026-08-08"
        assert by_mode["agent-security"].mode == "agent-security"


class TestLabels:
    def test_rows_carry_their_project_label_and_tags(self, seeded):
        from yeaboi.context.labels import LabelStore

        with LabelStore(seeded["db"]) as labels:
            labels.set_labels("planning", "p1", project="apollo", tags=("q3",))
            labels.set_labels("standup", "p1", "1", project="apollo", tags=("mode:standup",))
            labels.set_labels("performance", "", "prep:1", project="borealis")
        by_mode = {r.mode: r for r in recent_sessions(db_path=seeded["db"])}
        assert by_mode["planning"].project_label == "apollo" and by_mode["planning"].tags == ("q3",)
        assert by_mode["standup"].tags == ("mode:standup",)
        assert by_mode["performance"].project_label == "borealis"
        assert by_mode["retro"].project_label == "" and by_mode["retro"].tags == ()

    def test_a_project_label_narrows_the_list(self, seeded):
        from yeaboi.context.labels import LabelStore

        with LabelStore(seeded["db"]) as labels:
            labels.set_labels("planning", "p1", project="apollo")
            labels.set_labels("retro", "other", "1", project="borealis")
        rows = recent_sessions(project_label="apollo", db_path=seeded["db"])
        assert [(r.mode, r.session_id) for r in rows] == [("planning", "p1")]
        assert [r.session_id for r in recent_sessions(project_label="APOLLO", db_path=seeded["db"])] == ["p1"]
        assert recent_sessions(project_label="nobody", db_path=seeded["db"]) == []

    def test_a_missing_label_table_leaves_rows_unlabelled(self, seeded, monkeypatch):
        from yeaboi.context import labels as labels_module

        def boom(*args, **kwargs):
            raise RuntimeError("no labels")

        monkeypatch.setattr(labels_module.LabelStore, "list_labels", boom)
        rows = recent_sessions(db_path=seeded["db"])
        assert rows and all(r.project_label == "" for r in rows)

    def test_absent_modes_are_absent_not_invented(self, db):
        from yeaboi.sessions import SessionStore

        with SessionStore(db) as store:
            store.create_session("p1", "Apollo")
        rows = recent_sessions(db_path=db)
        assert [r.mode for r in rows] == ["planning"]

    def test_missing_database_is_empty(self, tmp_path):
        assert recent_sessions(db_path=tmp_path / "nope.db") == []


class TestOrdering:
    def test_newest_first(self, seeded):
        conn = sqlite3.connect(seeded["db"])
        conn.execute("UPDATE retro_history SET run_at = '2030-01-01T00:00:00+00:00'")
        conn.execute("UPDATE sessions_meta SET last_modified = '2000-01-01T00:00:00+00:00' WHERE session_id = 'a1'")
        conn.commit()
        conn.close()
        rows = recent_sessions(db_path=seeded["db"])
        assert rows[0].mode == "retro"
        assert rows[-1].mode == "analysis"

    def test_limit_caps_the_union(self, seeded):
        assert len(recent_sessions(limit=2, db_path=seeded["db"])) == 2

    def test_limit_zero_means_everything(self, seeded):
        assert len(recent_sessions(limit=0, db_path=seeded["db"])) == len(MODES)


class TestResilience:
    def test_a_broken_store_is_skipped(self, seeded, monkeypatch):
        from yeaboi import sessions_recent

        def boom(*args):
            raise RuntimeError("table gone")

        monkeypatch.setitem(sessions_recent._ADAPTERS, "retro", boom)
        rows = recent_sessions(db_path=seeded["db"])
        assert "retro" not in {r.mode for r in rows}
        assert "standup" in {r.mode for r in rows}
