"""Render tests for the context page (`_build_context_screen`): every branch, every size."""

from __future__ import annotations

import io

import pytest
from rich.console import Console
from rich.panel import Panel

from yeaboi.context.scope import SOURCES, ContextScope, Window
from yeaboi.ui.mode_select._context import CONTEXT_ACTIONS, ContextDraft, ContextPreview
from yeaboi.ui.mode_select.screens._screens_context import _build_context_screen
from yeaboi.ui.shared._components import STANDUP_THEME, standup_title


def _text(panel: Panel, width: int = 100, height: int = 40) -> str:
    console = Console(file=io.StringIO(), width=width, height=height, legacy_windows=False)
    console.print(panel)
    return console.file.getvalue()


def _preview() -> ContextPreview:
    return ContextPreview(counts={name: 3 for name in SOURCES}, label="3 standups · 3 retros", calendar_source="plan")


def _panel(draft: ContextDraft, **kw) -> Panel:
    """A builder call at the test console's size; the builder's own default is an 80×24 terminal."""
    return _build_context_screen(draft, _preview(), **{"width": 100, "height": 40, **kw})


class TestRender:
    def test_default_draft_lists_every_source_on(self):
        out = _text(_panel(ContextDraft()))
        for name in ("Sprint plans", "Standups", "Retros", "Weekly reviews"):
            assert name in out
        assert out.count("●") >= len(SOURCES) and "○" not in out
        assert "Reads 3 standups · 3 retros" in out and "sprint calendar from plan" in out
        for action in CONTEXT_ACTIONS:
            assert action in out

    def test_switched_off_source_is_hollow_and_uncounted(self):
        draft = ContextDraft(sources={"standup"})
        out = _text(_panel(draft))
        assert "○ Retros" in out and "● Standups" in out

    def test_incognito_says_so(self):
        out = _text(_panel(ContextDraft(sources=set())))
        assert "Incognito" in out

    @pytest.mark.parametrize(
        ("kind", "count", "expected"),
        [
            ("all", 1, "Everything"),
            ("sprints", 1, "Last sprint"),
            ("sprints", 3, "Last 3 sprints"),
            ("month", 1, "Last month"),
        ],
    )
    def test_window_row_names_the_kind(self, kind, count, expected):
        draft = ContextDraft(window_kind=kind, count=count)
        out = _text(_panel(draft, selected=len(SOURCES)))
        assert f"‹ {expected} ›" in out

    def test_custom_window_adds_the_date_fields(self):
        draft = ContextDraft(window_kind="custom", start="2026-06-01", end="2026-08-31")
        out = _text(_panel(draft, selected=len(SOURCES) + 1))
        assert "From" in out and "To" in out and "2026-06-01" in out and "▏" in out

    def test_project_and_tag_fields_and_message(self):
        draft = ContextDraft(project="Apollo", tags="q3, team-a", message="Every source on.")
        out = _text(_panel(draft, selected=len(SOURCES) + 2))
        assert "Apollo" in out and "q3, team-a" in out and "Every source on." in out

    def test_mode_theme_and_subtitle(self):
        panel = _panel(ContextDraft(), theme=STANDUP_THEME, title_fn=standup_title, mode="standup")
        out = _text(panel)
        assert "What this standup reads" in out
        assert isinstance(panel, Panel)

    @pytest.mark.parametrize(("width", "height"), [(84, 24), (100, 30), (60, 18), (140, 60)])
    def test_every_size_renders(self, width, height):
        draft = ContextDraft(window_kind="custom")
        panel = _panel(draft, selected=len(draft.rows()) - 1, width=width, height=height)
        assert isinstance(panel, Panel)
        _text(panel, width=width, height=height)


class TestDraft:
    def test_round_trips_a_scope(self):
        scope = ContextScope(
            sources=frozenset({"standup", "retro"}),
            window=Window(kind="sprints", count=2),
            projects=("Apollo",),
            tags=("q3",),
        )
        draft = ContextDraft.from_scope(scope)
        assert draft.rows()[-2:] == ["project", "tags"]
        assert draft.to_scope() == scope

    def test_toggle_materialises_all_on_first(self):
        draft = ContextDraft()
        draft.toggle("retro")
        assert draft.sources == set(SOURCES) - {"retro"}
        draft.toggle("retro")
        assert draft.sources == set(SOURCES)

    def test_cycle_window_wraps(self):
        draft = ContextDraft()
        draft.cycle_window(-1)
        assert draft.window_kind == "custom" and draft.rows()[-4:] == ["from", "to", "project", "tags"]
        draft.cycle_window(1)
        assert draft.window_kind == "all"

    def test_a_bad_custom_date_raises_on_use(self):
        draft = ContextDraft(window_kind="custom", start="yesterday")
        with pytest.raises(ValueError):
            draft.to_scope()

    def test_none_scope_is_the_empty_draft(self):
        assert ContextDraft.from_scope(None).to_scope() == ContextScope()
