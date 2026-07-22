"""Tests for tips rendering in the TUI: the mode-screen banner and inline hint."""

from rich.panel import Panel

from yeaboi.ui.mode_select.screens._screens import _build_mode_screen, _build_tip_rows
from yeaboi.ui.session.screens._screens_input import _image_hint, _voice_hint
from yeaboi.ui.shared import _tips
from yeaboi.voice import voice_install_command


def _tip_rows_text(**kwargs) -> str:
    """Rendered plain text of both tip rows joined, for substring assertions."""
    return "\n".join(t.plain for t in _build_tip_rows(**kwargs))


def test_voice_hint_empty_when_tips_disabled(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: False)
    assert _voice_hint() == ""


def test_image_hint_empty_when_tips_disabled(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: False)
    assert _image_hint() == ""


def test_image_hint_mentions_ctrl_v(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)
    hint = _image_hint()
    assert "Ctrl+V" in hint
    assert "screenshot" in hint


def test_image_hint_warns_off_cmd_v_on_macos(monkeypatch):
    """Mac users would reach for Cmd+V — the hint must steer them to Ctrl+V."""
    import sys

    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert "not ⌘V" in _image_hint()


def test_image_hint_no_cmd_warning_on_linux(monkeypatch):
    import sys

    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)
    monkeypatch.setattr(sys, "platform", "linux")
    assert "⌘" not in _image_hint()


def test_standup_input_screen_image_hint_gated(monkeypatch):
    """The standup input screen shows the Ctrl+V hint only for image-enabled fields."""
    import io

    from rich.console import Console

    from yeaboi.ui.mode_select.screens._screens_secondary import _build_standup_input_screen

    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)

    def _rendered(**kwargs) -> str:
        buf = io.StringIO()
        Console(file=buf, width=200, height=30).print(_build_standup_input_screen("Update?", "", **kwargs))
        return buf.getvalue()

    assert "Ctrl+V" in _rendered(show_image_hint=True)
    assert "Ctrl+V" not in _rendered(show_image_hint=False)


def test_voice_hint_present_when_available_and_enabled(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)
    monkeypatch.setattr("yeaboi.voice.is_voice_available", lambda: (True, ""))
    hint = _voice_hint()
    assert "double-tap Space" in hint


def test_voice_hint_shows_install_when_unavailable(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)
    monkeypatch.setattr("yeaboi.voice.is_voice_available", lambda: (False, "x"))
    hint = _voice_hint()
    # Hint shows the install-method-aware command (not a hardcoded `uv sync`).
    assert "dictate:" in hint
    assert voice_install_command() in hint


def test_mode_screen_renders_with_tips_on(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)
    result = _build_mode_screen(0, width=80, height=24, shimmer_tick=0.0)
    assert isinstance(result, Panel)


def test_mode_screen_renders_with_tips_off(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: False)
    result = _build_mode_screen(0, width=80, height=24, shimmer_tick=0.0)
    assert isinstance(result, Panel)


def test_mode_screen_renders_at_various_ticks(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)
    for tick in (0.0, 6.5, 42.0):
        result = _build_mode_screen(0, width=80, height=24, shimmer_tick=tick)
        assert isinstance(result, Panel)


def test_tip_rows_blank_when_disabled(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: False)
    rows = _build_tip_rows(0.0)
    assert [t.plain for t in rows] == ["", ""]


def test_tip_rows_show_browse_and_hide_hints(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)
    text = _tip_rows_text(shimmer_tick=0.0)
    assert "browse" in text
    assert "hide" in text


def test_tip_rows_show_compact_counter_not_dots(monkeypatch):
    # The position indicator is a fixed-width "n/total" counter, not one dot per
    # tip (which grew unboundedly as tips were added).
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)
    monkeypatch.setattr("yeaboi.voice.is_voice_available", lambda: (True, ""))
    _tips.get_tips.cache_clear()
    total = _tips.tip_count()
    text = _tip_rows_text(shimmer_tick=0.0, tip_override=2)
    assert f"3/{total}" in text  # override=2 → 1-based "3"
    assert "●" not in text and "○" not in text  # no per-tip dots
    _tips.get_tips.cache_clear()


def test_tip_rows_open_hint_only_for_carded_tip(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)
    monkeypatch.setattr("yeaboi.voice.is_voice_available", lambda: (True, ""))
    _tips.get_tips.cache_clear()
    tips = _tips.get_tips()
    carded = next(i for i, t in enumerate(tips) if t.mode_key is not None)
    ambient = next(i for i, t in enumerate(tips) if t.mode_key is None)
    assert "open" in _tip_rows_text(shimmer_tick=0.0, tip_override=carded)
    assert "open" not in _tip_rows_text(shimmer_tick=0.0, tip_override=ambient)
    _tips.get_tips.cache_clear()


def test_tip_rows_new_badge_when_flagged(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)
    monkeypatch.setattr("yeaboi.voice.is_voice_available", lambda: (True, ""))
    _tips.get_tips.cache_clear()
    tips = _tips.get_tips()
    new_idx = next(i for i, t in enumerate(tips) if t.is_new)
    plain_idx = next(i for i, t in enumerate(tips) if not t.is_new)
    assert "NEW" in _tip_rows_text(shimmer_tick=0.0, tip_override=new_idx)
    assert "NEW" not in _tip_rows_text(shimmer_tick=0.0, tip_override=plain_idx)
    _tips.get_tips.cache_clear()


def test_tip_override_pins_the_tip(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)
    monkeypatch.setattr("yeaboi.voice.is_voice_available", lambda: (True, ""))
    _tips.get_tips.cache_clear()
    tips = _tips.get_tips()
    # A large tick would auto-rotate away from index 2, but the override pins it.
    text = _tip_rows_text(shimmer_tick=999.0, tip_override=2)
    assert tips[2].text in text
    _tips.get_tips.cache_clear()
