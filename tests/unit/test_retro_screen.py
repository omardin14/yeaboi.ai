"""Render tests for the Retro TUI screen builder, theme, and page wiring."""

from rich.panel import Panel
from rich.text import Text

from scrum_agent.retro.board import RetroBoard
from scrum_agent.ui.mode_select.screens._screens import _MODE_CARDS
from scrum_agent.ui.mode_select.screens._screens_secondary import _build_retro_screen
from scrum_agent.ui.shared._components import RETRO_THEME, retro_title


class TestComponents:
    def test_theme_is_teal(self):
        assert RETRO_THEME.accent == "rgb(80,190,190)"

    def test_title_returns_text(self):
        assert isinstance(retro_title(), Text)

    def test_mode_card_registered(self):
        keys = {c["key"] for c in _MODE_CARDS}
        assert "retro" in keys

    def test_color_registered(self):
        from scrum_agent.ui.shared._animations import COLOR_RGB

        assert COLOR_RGB["rgb(80,190,190)"] == (80, 190, 190)

    def test_button_colors_registered(self):
        from scrum_agent.ui.shared._components import _BTN_COLORS

        assert "Generate Action Items" in _BTN_COLORS and "Close" in _BTN_COLORS


def _data(board):
    return {
        "session_name": "demo-2026-07-10",
        "display_code": "A3F9-1B2C",
        "url": "http://192.168.1.24:5173/?token=x",
        "message": "Server ready",
        "grids": board.cards_by_grid(),
    }


class TestBuildRetroScreen:
    def test_returns_panel_with_cards(self):
        b = RetroBoard("s")
        b.add_card(grid="went_well", text="ci is fast", author="Sam")
        b.add_ai_cards(["fix flaky tests"])
        panel = _build_retro_screen(_data(b), width=100, height=30)
        assert isinstance(panel, Panel)

    def test_handles_empty_grids(self):
        panel = _build_retro_screen(
            {"session_name": "", "display_code": "—", "url": "—", "message": "", "grids": {}},
            width=80,
            height=24,
        )
        assert isinstance(panel, Panel)

    def test_scroll_offset_accepted(self):
        b = RetroBoard("s")
        for i in range(40):
            b.add_card(grid="demos", text=f"card {i}", author="x")
        panel = _build_retro_screen(_data(b), width=80, height=20, scroll_offset=10, action_sel=1)
        assert isinstance(panel, Panel)

    def test_remote_url_and_custom_actions(self):
        b = RetroBoard("s")
        data = _data(b)
        data["public_url"] = "https://calm-tree-1234.trycloudflare.com/?token=x"
        data["actions"] = ["Generate Action Items", "Stop Sharing", "Export", "Close"]
        panel = _build_retro_screen(data, width=100, height=30, action_sel=1)
        assert isinstance(panel, Panel)

    def test_missing_optional_keys_default(self):
        # public_url / actions absent — must not raise (backward-compatible builder).
        panel = _build_retro_screen(
            {"session_name": "x", "display_code": "A-B", "url": "u", "message": "", "grids": {}},
            width=80,
            height=24,
        )
        assert isinstance(panel, Panel)
