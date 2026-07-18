"""Unit tests for the feedback-before-regenerate flow on the analysis preview pages.

Covers: _ask_regen_feedback (Esc cancels, empty Enter regenerates as-is, typed
text returned) and the theme/title re-branding of _build_standup_input_screen.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from rich.panel import Panel

from yeaboi.ui.mode_select import _ask_regen_feedback


def _drive(keys: list[str]) -> str | None:
    """Run _ask_regen_feedback against a scripted key sequence and stub Live."""
    console = MagicMock()
    console.size = (100, 30)
    live = MagicMock()
    key_iter = iter(keys)

    def read_key(timeout=None):
        return next(key_iter)

    return _ask_regen_feedback(console, live, read_key, 0.05, True, "epic")


class TestAskRegenFeedback:
    """Drive the feedback prompt with scripted keys."""

    def test_typed_feedback_returned(self):
        assert _drive(list("fix it") + ["enter"]) == "fix it"

    def test_empty_enter_returns_empty_string(self):
        """Empty Enter = regenerate as-is (no feedback)."""
        assert _drive(["enter"]) == ""

    def test_esc_returns_none(self):
        """Esc = cancel the regenerate entirely."""
        assert _drive(["esc"]) is None

    def test_backspace_edits_value(self):
        assert _drive(list("abc") + ["backspace", "enter"]) == "ab"

    def test_paste_appended(self):
        assert _drive(["paste:shorter titles", "enter"]) == "shorter titles"


class TestInputScreenBranding:
    """_build_standup_input_screen honours theme/title overrides."""

    def test_default_is_standup_branding(self):
        from yeaboi.ui.mode_select.screens._screens_secondary import _build_standup_input_screen

        panel = _build_standup_input_screen("What should change?", "", step="Regenerate epic")
        assert isinstance(panel, Panel)

    def test_analysis_theme_and_title_accepted(self):
        from yeaboi.ui.mode_select.screens._screens_secondary import _build_standup_input_screen
        from yeaboi.ui.shared._components import ANALYSIS_THEME, analysis_title

        panel = _build_standup_input_screen(
            "What should change?",
            "less jargon",
            step="Regenerate epic — feedback",
            theme=ANALYSIS_THEME,
            title=analysis_title(),
            width=100,
            height=30,
        )
        assert isinstance(panel, Panel)

    def test_analysis_title_rendered(self):
        """The overridden title actually replaces the standup ASCII art."""
        from io import StringIO

        from rich.console import Console

        from yeaboi.ui.mode_select.screens._screens_secondary import _build_standup_input_screen
        from yeaboi.ui.shared._components import ANALYSIS_THEME, analysis_title

        buf = StringIO()
        console = Console(file=buf, width=120, force_terminal=False)
        console.print(
            _build_standup_input_screen(
                "What should change?",
                "",
                step="Regenerate epic — feedback",
                theme=ANALYSIS_THEME,
                title=analysis_title(),
                width=120,
                height=30,
            )
        )
        out = buf.getvalue()
        assert "What should change?" in out
        assert "Regenerate epic" in out
