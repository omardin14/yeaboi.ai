"""Render tests for the Reporting TUI screen builder."""

import io

from rich.console import Console
from rich.panel import Panel

from scrum_agent.ui.mode_select.screens._screens_secondary import _build_reporting_screen


def _render(panel: Panel) -> str:
    console = Console(file=io.StringIO(), width=100)
    console.print(panel)
    return console.file.getvalue()


class TestBuildReportingScreen:
    def test_picker_view_renders_periods_and_actions(self):
        data = {
            "session_name": "Demo",
            "view": "picker",
            "periods": [
                ("last_sprint", "Last sprint", "recent sprint"),
                ("last_month", "Last month (~2 sprints)", "last ~4 weeks"),
            ],
            "selected_idx": 1,
            "theme": "aurora",
            "actions": ["Generate Report", "Theme", "Back"],
        }
        panel = _build_reporting_screen(data, width=100, height=32, action_sel=0)
        assert isinstance(panel, Panel)
        out = _render(panel)
        assert "Last sprint" in out
        assert "Last month" in out
        assert "aurora" in out  # current deck theme shown
        assert "Generate" in out  # action button present

    def test_detail_view_renders_report_lines(self):
        data = {
            "view": "detail",
            "detail_title": "Delivery Report — Last sprint",
            "detail_lines": ["Executive summary:", "  We shipped SSO.", "Highlights:", "  • SSO live"],
            "theme": "midnight",
            "actions": ["Export", "Theme", "Back"],
        }
        panel = _build_reporting_screen(data, width=100, height=32, action_sel=0)
        assert isinstance(panel, Panel)
        out = _render(panel)
        assert "SSO" in out
        assert "Export" in out

    def test_detail_view_empty_data(self):
        data = {"view": "detail", "detail_lines": [], "detail_title": "X", "actions": ["Export", "Theme", "Back"]}
        panel = _build_reporting_screen(data, width=100, height=30)
        assert isinstance(panel, Panel)
        out = _render(panel)
        assert "nothing to show" in out.lower()

    def test_sprint_select_view_renders_checkboxes(self):
        from scrum_agent.reporting.sprints import SprintRef

        sprints = [
            SprintRef("Sprint 5", "2026-06-01", "2026-06-14", "jira", in_quarter=False),
            SprintRef("Sprint 6", "2026-07-01", "2026-07-14", "jira", in_quarter=True),
        ]
        data = {
            "view": "sprint_select",
            "quarter_label": "Q3 2026",
            "sprints": sprints,
            "sprint_cursor": 1,
            "sprint_checked": {1},
            "actions": ["Generate Report", "Back"],
        }
        panel = _build_reporting_screen(data, width=100, height=32, action_sel=0)
        assert isinstance(panel, Panel)
        out = _render(panel)
        assert "Q3 2026" in out
        assert "Sprint 6" in out
        assert "■" in out and "□" in out  # one checked, one not
        assert "in quarter" in out
        assert "toggle" in out  # the hint line

    def test_sprint_select_empty(self):
        data = {
            "view": "sprint_select",
            "quarter_label": "Q3 2026",
            "sprints": [],
            "sprint_cursor": 0,
            "sprint_checked": set(),
            "actions": ["Generate Report", "Back"],
        }
        panel = _build_reporting_screen(data, width=100, height=30)
        assert isinstance(panel, Panel)
        assert "No sprints found" in _render(panel)

    def test_scrollable_long_detail(self):
        lines = [f"line {i}" for i in range(80)]
        data = {"view": "detail", "detail_lines": lines, "detail_title": "X", "actions": ["Export", "Theme", "Back"]}
        panel = _build_reporting_screen(data, width=100, height=24, scroll_offset=5)
        assert isinstance(panel, Panel)
        # Must not raise and must build a bounded viewport.
        _render(panel)
