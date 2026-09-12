"""Tests for src/yeaboi/context/labels.py — the central session_labels table and the tag vocabulary."""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from yeaboi.context.labels import (
    LABEL_MODES,
    SESSION_LABELS_SCHEMA,
    LabelStore,
    SessionLabels,
    default_tags,
    drop_run_labels,
    normalize_tag,
    normalize_tags,
)
from yeaboi.context.scope import ContextScope

TODAY = date(2026, 9, 11)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "sessions.db"


class TestNormalize:
    @pytest.mark.parametrize(
        ("raw", "tag"),
        [
            ("  Team A ", "team-a"),
            ("Q3", "q3"),
            ("sprint:12", "sprint:12"),
            ("weird!!chars##", "weirdchars"),
            ("--dash--", "dash"),
            ("x" * 50, "x" * 40),
            ("", ""),
            ("!!!", ""),
        ],
    )
    def test_normalize_tag(self, raw, tag):
        assert normalize_tag(raw) == tag

    def test_normalize_tags_sorts_dedupes_and_drops_blanks(self):
        assert normalize_tags(["Q3", "q3", "", "Team A"]) == ("q3", "team-a")
        assert normalize_tags("b, a ,,") == ("a", "b")
        assert normalize_tags(None) == ()


class TestDefaultTags:
    def test_always_present(self):
        assert default_tags("standup", today=TODAY) == ("2026-09", "mode:standup", "world:team")

    def test_solo_world_and_sprint_and_tracker(self):
        tags = default_tags("retro", today=TODAY, world="solo", sprint_number=12, tracker_key="PROJ")
        assert "world:solo" in tags and "sprint:12" in tags and "tracker:proj" in tags

    def test_per_mode_extras(self):
        assert "size:small" in default_tags("planning", today=TODAY, plan_size="small_project")
        assert "size:large" in default_tags("planning", today=TODAY, plan_size="smart")
        perf = default_tags("performance", today=TODAY, engineer="Ana Lopez", kind="prep")
        assert "engineer:ana-lopez" in perf and "kind:1on1" in perf
        assert "kind:review" in default_tags("performance", today=TODAY, kind="review")
        assert "period:last_sprint" in default_tags("reporting", today=TODAY, period="last_sprint")
        assert "week:2026-w37" in default_tags("review", today=TODAY, week_label="2026-W37")
        assert "source:jira" in default_tags("poker", today=TODAY, source="jira")
        assert "sprint-day:3" in default_tags("standup", today=TODAY, sprint_day=3)

    def test_extras_do_not_leak_across_modes(self):
        tags = default_tags("standup", today=TODAY, plan_size="smart", engineer="x", period="p", week_label="w")
        assert tags == ("2026-09", "mode:standup", "world:team")


class TestStore:
    def test_schema_is_created_by_the_store_and_is_idempotent(self, db):
        with LabelStore(db):
            pass
        with LabelStore(db) as store:
            store.set_labels("standup", "s1", "1", project="Apollo")
        names = {r[0] for r in sqlite3.connect(db).execute("SELECT name FROM sqlite_master").fetchall()}
        assert "session_labels" in names and "idx_session_labels_project" in names
        assert "PRIMARY KEY (mode, session_id, run_id)" in SESSION_LABELS_SCHEMA

    def test_set_get_round_trip(self, db):
        scope = ContextScope(sources=frozenset({"standup"}))
        with LabelStore(db) as store:
            saved = store.set_labels("standup", "s1", "7", project="Apollo", tags=["Q3", "team a"], scope=scope)
            loaded = store.get_labels("standup", "s1", "7")
        assert saved == loaded
        assert isinstance(loaded, SessionLabels)
        assert loaded.project == "Apollo" and loaded.tags == ("q3", "team-a")
        assert loaded.scope == scope.to_dict()
        assert loaded.created_at and loaded.updated_at
        assert loaded.to_dict()["project_label"] == "Apollo"

    def test_missing_row_is_none(self, db):
        with LabelStore(db) as store:
            assert store.get_labels("standup", "nope") is None

    def test_merge_keeps_old_tags_and_project(self, db):
        with LabelStore(db) as store:
            store.set_labels("planning", "p1", project="Apollo", tags=["a"])
            merged = store.set_labels("planning", "p1", tags=["b"])
            assert merged.tags == ("a", "b") and merged.project == "Apollo"
            replaced = store.set_labels("planning", "p1", project="Zeus", tags=["c"], merge_tags=False)
            assert replaced.tags == ("c",) and replaced.project == "Zeus"

    def test_scope_is_kept_when_not_given_again(self, db):
        with LabelStore(db) as store:
            store.set_labels("planning", "p1", scope={"sources": None})
            again = store.set_labels("planning", "p1", tags=["x"])
        assert again.scope == {"sources": None}

    def test_project_none_keeps_and_blank_clears(self, db):
        with LabelStore(db) as store:
            store.set_labels("planning", "p1", project="Apollo")
            assert store.set_labels("planning", "p1", tags=["x"]).project == "Apollo"
            assert store.set_labels("planning", "p1", project=None).project == "Apollo"
            assert store.set_labels("planning", "p1", project="").project == ""

    def test_find_ids_ignores_case(self, db):
        with LabelStore(db) as store:
            store.set_labels("standup", "s1", "1", project="Apollo")
            assert store.find_ids("standup", projects=["APOLLO"]) == {"1"}
            assert store.find_ids("standup", projects=["apollo two"]) == set()

    def test_unknown_mode_and_empty_key_raise(self, db):
        with LabelStore(db) as store:
            with pytest.raises(ValueError, match="unknown label mode"):
                store.set_labels("chat", "s1")
            with pytest.raises(ValueError, match="needs a session_id"):
                store.set_labels("standup", "")
        assert "planning" in LABEL_MODES

    def test_find_ids(self, db):
        with LabelStore(db) as store:
            store.set_labels("standup", "s1", "1", project="Apollo", tags=["q3"])
            store.set_labels("standup", "s1", "2", project="Apollo", tags=["q3", "team-a"])
            store.set_labels("standup", "s1", "3", project="Zeus", tags=["q3"])
            store.set_labels("planning", "p1", project="Apollo")
            assert store.find_ids("standup", projects=["apollo"]) == {"1", "2"}
            assert store.find_ids("standup", tags=["Q3", "team a"]) == {"2"}
            assert store.find_ids("standup", projects=["Zeus"], tags=["q3"]) == {"3"}
            assert store.find_ids("planning") == {"p1"}
            assert store.find_ids("retro") == set()

    def test_list_labels_filters_and_orders_newest_first(self, db):
        with LabelStore(db) as store:
            store.set_labels("standup", "s1", "1", project="Apollo", tags=["q3"])
            store.set_labels("retro", "s1", "9", project="Apollo", tags=["q3", "x"])
            rows = store.list_labels()
            assert [r.run_id for r in rows] == ["9", "1"]
            assert [r.mode for r in store.list_labels(mode="retro")] == ["retro"]
            assert [r.run_id for r in store.list_labels(tags=["x"])] == ["9"]
            assert store.list_labels(project="Nope") == []
            assert len(store.list_labels(limit=1)) == 1

    def test_projects_and_tags_autocomplete(self, db):
        with LabelStore(db) as store:
            store.set_labels("standup", "s1", "1", project="Apollo", tags=["q3"])
            store.set_labels("standup", "s1", "2", project="Ares", tags=["q3", "team-a"])
            store.set_labels("standup", "s1", "3", tags=["q3"])
            assert store.list_projects() == ["Ares", "Apollo"]
            assert store.list_projects(prefix="ap") == ["Apollo"]
            assert store.list_projects(limit=1) == ["Ares"]
            assert store.list_tags() == [("q3", 3), ("team-a", 1)]
            assert store.list_tags(prefix="team") == [("team-a", 1)]

    def test_delete_by_run_and_by_session(self, db):
        with LabelStore(db) as store:
            store.set_labels("standup", "s1", "1")
            store.set_labels("standup", "s1", "2")
            store.set_labels("standup", "s2", "3")
            assert store.delete("standup", run_id="1")
            assert store.delete("standup", session_id="s1")
            assert store.get_labels("standup", "s1", "2") is None
            assert store.delete("standup", "s2", "3")
            assert not store.delete("standup", "s2", "3")
            with pytest.raises(ValueError):
                store.delete("standup")

    def test_unreadable_json_columns_degrade(self, db):
        with LabelStore(db) as store:
            store.set_labels("standup", "s1", "1", tags=["a"])
        conn = sqlite3.connect(db)
        conn.execute("UPDATE session_labels SET tags_json = 'junk', scope_json = '{bad'")
        conn.commit()
        conn.close()
        with LabelStore(db) as store:
            row = store.get_labels("standup", "s1", "1")
        assert row.tags == () and row.scope is None


class TestDropRunLabels:
    def test_drops_the_row(self, db):
        with LabelStore(db) as store:
            store.set_labels("retro", "s1", "4")
        drop_run_labels(db, "retro", 4)
        with LabelStore(db) as store:
            assert store.get_labels("retro", "s1", "4") is None

    def test_never_raises(self, tmp_path):
        drop_run_labels(tmp_path / "missing-dir" / "sessions.db", "retro", 1)


class TestLabelRun:
    def test_a_blank_label_at_record_time_keeps_the_old_one(self, db):
        from yeaboi.context.labels import label_run

        with LabelStore(db) as store:
            store.set_labels("standup", "s1", "7", project="Apollo")
        label_run("standup", "s1", "7", project_label="", tags=(), scope=None, defaults={"today": TODAY}, db_path=db)
        with LabelStore(db) as store:
            assert store.get_labels("standup", "s1", "7").project == "Apollo"

    def test_writes_the_defaults_and_the_users_tags(self, db):
        from datetime import date

        from yeaboi.context.labels import LabelStore, label_run
        from yeaboi.context.scope import ContextScope

        scope = ContextScope(sources=frozenset({"retro"}))
        row = label_run(
            "standup",
            "s1",
            7,
            project_label="Apollo",
            tags=["Q3 Push"],
            scope=scope,
            defaults={"sprint_day": 3, "today": date(2026, 9, 11)},
            db_path=db,
        )
        assert row is not None
        assert {"mode:standup", "world:team", "2026-09", "sprint-day:3", "q3-push"} <= set(row.tags)
        assert row.project == "Apollo" and row.scope == scope.to_dict()
        with LabelStore(db) as store:
            assert store.get_labels("standup", "s1", "7") == row

    def test_an_unscoped_run_clears_the_old_scope(self, db):
        from yeaboi.context.labels import LabelStore, label_run
        from yeaboi.context.scope import ContextScope

        label_run("retro", "s1", 1, scope=ContextScope(sources=frozenset({"plan"})), db_path=db)
        label_run("retro", "s1", 1, db_path=db)
        with LabelStore(db) as store:
            assert store.get_labels("retro", "s1", "1").scope is None

    def test_never_raises(self, tmp_path):
        from yeaboi.context.labels import label_run

        assert label_run("standup", "s1", 1, db_path=tmp_path) is None  # a directory is not a database


class TestProjectLabelCase:
    def test_list_labels_matches_the_project_in_any_case(self, db):
        from yeaboi.context.labels import LabelStore

        with LabelStore(db) as store:
            store.set_labels("standup", "s1", "1", project="apollo")
            assert [r.run_id for r in store.list_labels(project="Apollo")] == ["1"]
            assert [r.run_id for r in store.list_labels(project="APOLLO", mode="standup")] == ["1"]
            assert store.list_labels(project="zeus") == []

    def test_the_engine_list_matches_the_same_way(self, tmp_path):
        from yeaboi.context.engine import list_session_labels, set_session_labels

        path = tmp_path / "labels.db"
        set_session_labels("standup", "s1", "1", project_label="apollo", db_path=path)
        assert [r.run_id for r in list_session_labels(project_label="Apollo", db_path=path)] == ["1"]
