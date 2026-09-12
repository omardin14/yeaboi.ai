"""The TUI planning intake labels its plan the way a headless run does."""

from __future__ import annotations

import pytest

from yeaboi.context.labels import LabelStore
from yeaboi.ui.session import label_new_plan


@pytest.fixture
def db(tmp_path):
    return tmp_path / "sessions.db"


class TestLabelNewPlan:
    def test_the_row_carries_the_defaults_the_label_and_the_scope(self, db, monkeypatch):
        monkeypatch.setattr("yeaboi.config.is_solo_mode", lambda: False)
        label_new_plan("p1", "smart", context="standup@month", project_label="apollo", db_path=db)
        with LabelStore(db) as store:
            row = store.get_labels("planning", "p1")
        assert row is not None and row.project == "apollo"
        assert {"mode:planning", "world:team", "size:large"} <= set(row.tags)
        assert row.scope is not None and row.scope["sources"] == ["standup"]

    def test_a_small_plan_in_the_solo_world(self, db, monkeypatch):
        monkeypatch.setattr("yeaboi.config.is_solo_mode", lambda: True)
        label_new_plan("p2", "small_project", db_path=db)
        with LabelStore(db) as store:
            row = store.get_labels("planning", "p2")
        assert row is not None and {"world:solo", "size:small"} <= set(row.tags)

    def test_a_failing_label_never_blocks_the_session(self, db, monkeypatch):
        def boom(*_a, **_kw):
            raise RuntimeError("disk full")

        monkeypatch.setattr("yeaboi.context.labels.label_run", boom)
        label_new_plan("p3", "smart", db_path=db)  # returns, logs, raises nothing
