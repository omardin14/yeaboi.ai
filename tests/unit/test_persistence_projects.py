"""projects.json remembers which engine project a planning run happened inside."""

from __future__ import annotations

import pytest

from yeaboi import persistence


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(persistence, "_PROJECTS_FILE", tmp_path / "projects.json")
    monkeypatch.setattr(persistence, "save_graph_state", lambda *a, **k: None)
    monkeypatch.setattr("yeaboi.paths.get_db_path", lambda: tmp_path / "sessions.db")
    return tmp_path


class TestEngineProjectStamp:
    def test_a_scoped_run_carries_its_engine_project(self, home):
        persistence.save_project_snapshot("uuid-1", {"project_id": "proj-0000aaaa", "messages": []})
        (row,) = persistence.load_projects()
        assert row.id == "uuid-1" and row.engine_project_id == "proj-0000aaaa"

    def test_an_unscoped_run_is_blank(self, home):
        persistence.save_project_snapshot("uuid-2", {"messages": []})
        (row,) = persistence.load_projects()
        assert row.engine_project_id == ""

    def test_an_old_entry_without_the_key_still_loads(self, home):
        (home / "projects.json").write_text(
            '{"version": 1, "projects": [{"id": "old", "name": "Old", "updated_at": "2026-01-01"}]}'
        )
        (row,) = persistence.load_projects()
        assert row.name == "Old" and row.engine_project_id == ""


@pytest.fixture()
def real_states(tmp_path, monkeypatch):
    """Like `home`, but the state writer is real and lands on disk."""
    monkeypatch.setattr(persistence, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(persistence, "_PROJECTS_FILE", tmp_path / "projects.json")
    monkeypatch.setattr(persistence, "_STATES_DIR", tmp_path / "states")
    monkeypatch.setattr("yeaboi.paths.get_db_path", lambda: tmp_path / "sessions.db")
    return tmp_path


class TestStoreUnion:
    """The list also shows plans the app's chat keeps in the session store."""

    def _store_plan(self, home, session_id="new-abcd1234-2026-09-11", **meta):
        from yeaboi.sessions import SessionStore

        with SessionStore(home / "sessions.db") as store:
            store.create_session(session_id, meta.get("project_name", ""), title=meta.get("title", ""))
            if meta.get("last_node"):
                store.update_last_node(session_id, meta["last_node"])
        return session_id

    def test_a_store_plan_is_listed_under_its_title(self, home):
        self._store_plan(home, title="Barbers", last_node="story_writer")
        (row,) = persistence.load_projects()
        assert row.name == "Barbers" and row.id == "new-abcd1234-2026-09-11"
        assert row.status == "In Progress" and row.progress == "5/7 stages complete"

    def test_a_nameless_plan_falls_back_to_the_display_name(self, home):
        self._store_plan(home, project_name="Apollo")
        (row,) = persistence.load_projects()
        assert row.name.startswith("apollo")

    def test_a_plan_in_both_stores_is_listed_once(self, home):
        persistence.save_project_snapshot("uuid-1", {"messages": []})
        self._store_plan(home, session_id="uuid-1", title="Twice")
        rows = persistence.load_projects()
        assert [r.id for r in rows] == ["uuid-1"]

    def test_no_store_means_no_extra_rows(self, home, monkeypatch):
        monkeypatch.setattr("yeaboi.paths.get_db_path", lambda: home / "missing" / "nope.db")
        persistence.save_project_snapshot("uuid-1", {"messages": []})
        assert [r.id for r in persistence.load_projects()] == ["uuid-1"]

    def test_deleting_a_store_only_plan_removes_its_row(self, home):
        from yeaboi.sessions import SessionStore

        sid = self._store_plan(home)
        assert persistence.delete_project(sid) is True
        with SessionStore(home / "sessions.db") as store:
            assert store.list_sessions() == []
        assert persistence.delete_project("never-existed") is False


class TestAllowlistedKeys:
    """State keys the file store used to drop between saves."""

    def test_solo_profile_dod_and_labels_survive(self, real_states):
        state = {
            "messages": [],
            "solo": True,
            "analysis_profile_id": "jira-PROJ",
            "custom_dod_items": ("Tests pass",),
            "selected_team_members": ("ann",),
            "_epic_reviewed": True,
            "context_scope": '{"sources": null}',
            "project_label": "apollo",
        }
        persistence.save_project_snapshot("uuid-3", state)
        back = persistence.load_graph_state("uuid-3")
        for key, value in state.items():
            if key != "messages":
                assert back[key] == value, key
        assert isinstance(back["custom_dod_items"], tuple)
