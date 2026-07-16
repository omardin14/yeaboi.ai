"""Tests for tips rendering in the TUI: the mode-screen banner and inline hint."""

from rich.panel import Panel

from yeaboi.ui.mode_select.screens._screens import _build_mode_screen
from yeaboi.ui.session.screens._screens_input import _voice_hint


def test_voice_hint_empty_when_tips_disabled(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: False)
    assert _voice_hint() == ""


def test_voice_hint_present_when_available_and_enabled(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)
    monkeypatch.setattr("yeaboi.voice.is_voice_available", lambda: (True, ""))
    hint = _voice_hint()
    assert "double-tap Space" in hint


def test_voice_hint_shows_install_when_unavailable(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)
    monkeypatch.setattr("yeaboi.voice.is_voice_available", lambda: (False, "x"))
    hint = _voice_hint()
    assert "uv sync --extra voice" in hint


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
