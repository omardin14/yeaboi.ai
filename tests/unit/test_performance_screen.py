"""Render tests for the Performance TUI screen builder."""

import io

from rich.console import Console
from rich.panel import Panel

from scrum_agent.ui.mode_select.screens._screens_secondary import _build_performance_screen


def _render(panel: Panel) -> str:
    console = Console(file=io.StringIO(), width=100)
    console.print(panel)
    return console.file.getvalue()


class TestBuildPerformanceScreen:
    def test_roster_view_renders_ascii_and_hint(self):
        # Engineer names render as big ASCII art (like the intake mode picker), so
        # the literal name text is NOT present — assert the panel builds and the
        # selected engineer's hint (rendered as plain text) shows.
        data = {
            "session_name": "Demo",
            "view": "roster",
            "roster": ["Ada Lovelace", "Alan Turing"],
            "roster_hints": ["2 open 1:1 actions", "no open 1:1 actions"],
            "selected_idx": 0,
            "actions": ["1:1 Prep", "1:1 Complete", "6mo Review", "Notes", "Export", "Back"],
        }
        # desc_reveal > 0 reveals the selected engineer's description (typewriter).
        panel = _build_performance_screen(data, width=120, height=40, action_sel=0, desc_reveal=100.0)
        assert isinstance(panel, Panel)
        out = _render(panel)
        assert "2 open 1:1 actions" in out  # selected engineer's description
        assert "1:1 Prep" in out  # action buttons still present

    def test_roster_windows_large_roster(self):
        # A long roster must not crash; ▼ marker shows there are more below.
        roster = [f"Person {i}" for i in range(20)]
        data = {"view": "roster", "roster": roster, "selected_idx": 0}
        panel = _build_performance_screen(data, width=120, height=30)
        assert isinstance(panel, Panel)
        out = _render(panel)
        assert "more" in out  # ▲/▼ overflow indicator

    def test_empty_roster_shows_hint(self):
        data = {"session_name": "Demo", "view": "roster", "roster": [], "selected_idx": 0}
        panel = _build_performance_screen(data, width=100, height=32)
        assert isinstance(panel, Panel)
        out = _render(panel)
        assert "No engineers" in out

    def test_detail_view_shows_artifact_lines(self):
        data = {
            "view": "detail",
            "detail_title": "1:1 Prep — Ada",
            "detail_lines": ["1:1 Prep — Ada", "", "Talking points:", "  • one", "  • two"],
            "actions": ["Export", "Back"],
        }
        panel = _build_performance_screen(data, width=100, height=32, action_sel=1)
        assert isinstance(panel, Panel)
        out = _render(panel)
        assert "Talking points" in out and "one" in out

    def test_detail_scrolls_without_error(self):
        lines = [f"line {i}" for i in range(100)]
        data = {"view": "detail", "detail_title": "x", "detail_lines": lines, "actions": ["Export", "Back"]}
        panel = _build_performance_screen(data, width=100, height=20, scroll_offset=40)
        assert isinstance(panel, Panel)
