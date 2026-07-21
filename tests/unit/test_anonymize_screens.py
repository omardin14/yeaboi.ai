"""Render tests for the Anonymize review screen + the generalized progress screen."""

from __future__ import annotations

from io import StringIO

from rich.console import Console
from rich.panel import Panel

from yeaboi.ui.mode_select.screens._screens_secondary import (
    _build_anonymize_review_screen,
    _build_standup_progress_screen,
)
from yeaboi.ui.shared._components import REPORTING_THEME, reporting_title


def _render(panel: Panel) -> str:
    console = Console(file=StringIO(), width=90, height=30)
    console.print(panel)
    return console.file.getvalue()


def _review_data(**over) -> dict:
    base = {
        "anonymized_text": "# Sprint plan\n\n- [PROJECT] epic\n- [TEAM] work",
        "replacements": [("Acme", "[COMPANY]"), ("Falcon", "[PROJECT]")],
        "warnings": [],
        "actions": ["Adjust", "Export", "Copy", "Back"],
        "message": "",
    }
    base.update(over)
    return base


class TestReviewScreen:
    def test_returns_panel(self):
        panel = _build_anonymize_review_screen(
            _review_data(), theme=REPORTING_THEME, title=reporting_title(), height=30
        )
        assert isinstance(panel, Panel)

    def test_renders_masked_text_and_replacements(self):
        out = _render(
            _build_anonymize_review_screen(_review_data(), theme=REPORTING_THEME, title=reporting_title(), height=30)
        )
        assert "Sprint plan" in out
        assert "masked" in out.lower()  # subtitle "N item(s) masked"
        # The "what was masked" summary shows originals (review-only).
        assert "Acme" in out

    def test_handles_empty_text(self):
        panel = _build_anonymize_review_screen(
            _review_data(anonymized_text="", replacements=[]),
            theme=REPORTING_THEME,
            title=reporting_title(),
            height=30,
        )
        assert isinstance(panel, Panel)
        out = _render(panel)
        assert "nothing to show" in out.lower()

    def test_scrolls_long_content(self):
        long_text = "\n".join(f"line {i}" for i in range(200))
        meta: dict = {}
        _build_anonymize_review_screen(
            _review_data(anonymized_text=long_text),
            theme=REPORTING_THEME,
            title=reporting_title(),
            height=30,
            scroll_offset=5,
            scroll_meta=meta,
        )
        # publish_geometry populated the scroll meta with a positive max offset.
        assert meta.get("max_offset", 0) > 0

    def test_renders_notices(self):
        out = _render(
            _build_anonymize_review_screen(
                _review_data(warnings=["AI masking unavailable — review manually."]),
                theme=REPORTING_THEME,
                title=reporting_title(),
                height=30,
            )
        )
        assert "Notices" in out


class TestProgressScreenTheming:
    def test_reuses_screen_with_custom_theme_and_label(self):
        panel = _build_standup_progress_screen(
            ["Masking sensitive data with the AI…"],
            width=90,
            height=24,
            theme=REPORTING_THEME,
            title=reporting_title(),
            label="Anonymizing output",
        )
        out = _render(panel)
        assert "Anonymizing output" in out

    def test_default_is_standup(self):
        panel = _build_standup_progress_screen(["Starting"], width=90, height=24)
        out = _render(panel)
        assert "Generating standup" in out
