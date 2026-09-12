"""The context page's key loop and the hub's use of it — scripted keys, no terminal."""

from __future__ import annotations

import pytest

from yeaboi.context.labels import LabelStore
from yeaboi.context.scope import ContextScope, Window
from yeaboi.ui.mode_select import _context as page


class _Console:
    size = (100, 40)


class _Live:
    def __init__(self):
        self.frames = 0

    def update(self, _panel):
        self.frames += 1


def _drive(keys, *, mode="standup", initial=None, db_path=None, monkeypatch=None):
    it = iter(keys)
    live = _Live()
    result = page.run_context_page(
        _Console(), live, lambda **_k: next(it), 0.001, True, mode=mode, initial=initial, db_path=db_path
    )
    return result, live


@pytest.fixture(autouse=True)
def _no_store_reads(monkeypatch):
    # The preview reads every store; the loop under test is the keys, not the stores.
    monkeypatch.setattr(page, "preview_draft", lambda draft, db_path=None: page.ContextPreview(label="nothing"))


class TestKeys:
    def test_esc_returns_none(self):
        result, live = _drive(["esc"])
        assert result is None and live.frames == 1

    def test_back_button_returns_none(self):
        result, _ = _drive(["left", "enter"])  # Use → Back (wraps left)
        assert result is None

    def test_use_returns_the_edited_scope(self):
        keys = [" ", "down", " "]  # plan off, standup off
        keys += ["down"] * 7 + ["right", "right"]  # to the window row; all → sprints → month
        keys += ["down", "A", "p", "o", "down", "q", "3", "enter"]  # project, tags, Use
        result, _ = _drive(keys)
        assert result == ContextScope(
            sources=frozenset(set(page.SOURCES) - {"plan", "standup"}),
            window=Window(kind="month"),
            projects=("Apo",),
            tags=("q3",),
        )

    def test_sprint_count_changes_with_plus_and_minus(self):
        keys = ["down"] * 8 + ["right", "+", "+", "-", "enter"]
        result, _ = _drive(keys)
        assert result.window == Window(kind="sprints", count=2)

    def test_all_on_button_resets_the_chips(self):
        result, _ = _drive([" ", "right", "enter", "left", "enter"])  # plan off, All on, back to Use, Use
        assert result.sources is None

    def test_incognito_then_use(self):
        result, _ = _drive(["right", "right", "enter", "left", "left", "enter"])
        assert result == ContextScope(sources=frozenset())

    def test_q_quits_only_off_a_text_row(self):
        assert _drive(["q"])[0] is None
        result, _ = _drive(["down"] * 9 + ["q", "enter"])
        assert result.projects == ("q",)

    def test_backspace_and_a_bad_date_keep_the_page_open(self):
        keys = ["down"] * 8 + ["left", "down", "x", "y", "backspace", "enter", "esc"]  # custom → From "x" → Use fails
        result, live = _drive(keys)
        assert result is None and live.frames == len(keys)

    def test_tab_completes_from_the_labels_in_use(self, tmp_path):
        db = tmp_path / "sessions.db"
        with LabelStore(db) as labels:
            labels.set_labels("retro", "p1", "3", project="Apollo", tags=["q3-push"])
        keys = ["down"] * 9 + ["a", "tab", "down", "q", "tab", "enter"]
        result, _ = _drive(keys, db_path=db)
        assert result.projects == ("Apollo",) and result.tags == ("q3-push",)

    def test_initial_scope_is_the_starting_draft(self):
        initial = ContextScope(sources=frozenset({"retro"}), window=Window(kind="year"))
        result, _ = _drive(["enter"], initial=initial)
        assert result == initial


class TestCompleteText:
    def test_no_database_leaves_the_text(self):
        assert page.complete_text("project", "ap") == "ap"

    def test_completes_the_last_comma_token(self, tmp_path):
        db = tmp_path / "sessions.db"
        with LabelStore(db) as labels:
            labels.set_labels("retro", "p1", "3", tags=["alpha", "beta"])
        assert page.complete_text("tags", "alpha, b", db_path=db) == "alpha, beta"
        assert page.complete_text("tags", "zz", db_path=db) == "zz"


class TestPreviewDraft:
    def test_reads_counts_and_label(self, tmp_path, monkeypatch):
        monkeypatch.undo()
        monkeypatch.setattr("yeaboi.context.window._from_tracker", lambda: None)
        preview = page.preview_draft(ContextDraft(sources={"retro"}), db_path=tmp_path / "sessions.db")
        assert preview.counts.get("retro") == 0 and preview.label

    def test_a_malformed_draft_reports_instead_of_raising(self, monkeypatch):
        monkeypatch.undo()
        preview = page.preview_draft(ContextDraft(window_kind="custom", start="nope"))
        assert "ISO" in preview.label and preview.counts == {}


ContextDraft = page.ContextDraft


class TestHubWiring:
    """The hub opens the page before a new run and keeps the answer for the mode."""

    @pytest.fixture
    def hub(self, tmp_path, monkeypatch):
        import os

        import yeaboi.ui.mode_select as mode_select

        db = tmp_path / "sessions.db"
        monkeypatch.setattr(mode_select, "_ana_dbp", db)
        for key in ("YEABOI_CONTEXT_RETRO", "YEABOI_CONTEXT_PLANNING"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setattr("yeaboi.config.set_config_value", lambda key, value: tmp_path / ".env")
        yield mode_select, db
        # set_last_context_scope writes os.environ directly; leave nothing behind.
        for key in ("YEABOI_CONTEXT_RETRO", "YEABOI_CONTEXT_PLANNING"):
            os.environ.pop(key, None)

    def test_new_run_opens_the_page_then_the_live_page(self, hub, monkeypatch):
        mode_select, db = hub
        from yeaboi.config import get_last_context_scope
        from yeaboi.ui.shared._components import RETRO_THEME, retro_title

        ran: list[str] = []
        scope = ContextScope(sources=frozenset({"standup"}))
        monkeypatch.setattr(page, "run_context_page", lambda *a, **k: scope)
        keys = iter(["enter", "esc"])  # Enter on the "+ New" card (no runs → index 0), then leave
        mode_select._run_mode_hub(
            _Console(),
            _Live(),
            lambda **_k: next(keys),
            0.001,
            True,
            mode="retro",
            title_fn=retro_title,
            subtitle="Saved retros",
            empty_title="No retros yet",
            empty_subtitle="Press Enter",
            new_label="+ New retro",
            load_runs=lambda: [],
            files_export=lambda r: {},
            get_document=lambda r: None,
            delete_run=lambda r: None,
            run_new=lambda: ran.append("retro"),
            share_theme=RETRO_THEME,
            context_mode="retro",
        )
        assert ran == ["retro"]
        assert get_last_context_scope("retro") == scope.to_dict()

    def test_backing_out_of_the_page_starts_nothing(self, hub, monkeypatch):
        mode_select, db = hub
        from yeaboi.ui.shared._components import RETRO_THEME, retro_title

        ran: list[str] = []
        monkeypatch.setattr(page, "run_context_page", lambda *a, **k: None)
        keys = iter(["enter", "esc"])
        mode_select._run_mode_hub(
            _Console(),
            _Live(),
            lambda **_k: next(keys),
            0.001,
            True,
            mode="retro",
            title_fn=retro_title,
            subtitle="Saved retros",
            empty_title="No retros yet",
            empty_subtitle="Press Enter",
            new_label="+ New retro",
            load_runs=lambda: [],
            files_export=lambda r: {},
            get_document=lambda r: None,
            delete_run=lambda r: None,
            run_new=lambda: ran.append("retro"),
            share_theme=RETRO_THEME,
            context_mode="retro",
        )
        assert ran == []

    def test_rows_carry_their_labels(self, hub):
        mode_select, db = hub
        from yeaboi.ui.mode_select.screens._project_cards import RunSummary
        from yeaboi.ui.shared._components import RETRO_THEME, retro_title

        with LabelStore(db) as labels:
            labels.set_labels("retro", "p1", "7", project="Apollo", tags=["q3", "mode:retro"])
        seen: list[list[RunSummary]] = []

        def load_runs():
            rows = [RunSummary("retro", 7, "Retro — 2026-09-05", "4 cards", "2 days ago")]
            seen.append(rows)
            return rows

        keys = iter(["esc"])
        mode_select._run_mode_hub(
            _Console(),
            _Live(),
            lambda **_k: next(keys),
            0.001,
            True,
            mode="retro",
            title_fn=retro_title,
            subtitle="Saved retros",
            empty_title="No retros yet",
            empty_subtitle="Press Enter",
            new_label="+ New retro",
            load_runs=load_runs,
            files_export=lambda r: {},
            get_document=lambda r: None,
            delete_run=lambda r: None,
            run_new=lambda: None,
            share_theme=RETRO_THEME,
            context_mode="retro",
        )
        assert seen[0][0].subtitle == "4 cards · Apollo · q3"

    def test_planning_context_helper_keeps_the_scope(self, hub, monkeypatch):
        mode_select, db = hub
        from yeaboi.config import get_last_context_scope

        monkeypatch.delenv("YEABOI_CONTEXT_PLANNING", raising=False)
        scope = ContextScope(sources=frozenset({"retro"}), window=Window(kind="quarter"))
        monkeypatch.setattr(page, "run_context_page", lambda *a, **k: scope)
        assert mode_select._pick_planning_context(_Console(), _Live(), lambda **_k: "esc", 0.001, True) == scope
        assert get_last_context_scope("planning") == scope.to_dict()
        # Backing out reads as last time — the plan still starts.
        monkeypatch.setattr(page, "run_context_page", lambda *a, **k: None)
        assert mode_select._pick_planning_context(_Console(), _Live(), lambda **_k: "esc", 0.001, True) == scope


class TestBoardPagesRecordTheirScope:
    """The retro and poker pages read under a selection; the run they record must say so."""

    def test_the_two_record_sites_pass_the_scope_they_read_under(self):
        from pathlib import Path

        import yeaboi.ui.mode_select as mode_select

        source = Path(mode_select.__file__).read_text()
        assert "record_retro_run(report, db_path=_ana_dbp, scope=selection.scope)" in source
        assert "record_poker_run(report, db_path=_ana_dbp, scope=board.selection.scope)" in source
