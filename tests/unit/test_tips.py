"""Tests for the rotating welcome-screen tips (ui/shared/_tips.py)."""

from scrum_agent.ui.shared import _tips
from scrum_agent.ui.shared._tips import (
    TIP_ROTATE_SECONDS,
    current_tip,
    get_tips,
    tip_brightness,
    tip_count,
)


def _clear_cache():
    # get_tips is lru_cached; reset so a monkeypatched availability is re-read.
    get_tips.cache_clear()


def test_get_tips_non_empty(monkeypatch):
    _clear_cache()
    monkeypatch.setattr("scrum_agent.voice.is_voice_available", lambda: (True, ""))
    tips = get_tips()
    assert len(tips) > 1
    assert all(isinstance(t, str) and t for t in tips)
    _clear_cache()


def test_voice_tip_when_available(monkeypatch):
    _clear_cache()
    monkeypatch.setattr("scrum_agent.voice.is_voice_available", lambda: (True, ""))
    voice_tip = get_tips()[0]
    assert "double-tap Space" in voice_tip
    _clear_cache()


def test_voice_tip_when_unavailable(monkeypatch):
    _clear_cache()
    monkeypatch.setattr("scrum_agent.voice.is_voice_available", lambda: (False, "reason"))
    voice_tip = get_tips()[0]
    assert "uv sync --extra voice" in voice_tip
    _clear_cache()


def test_music_tip_when_available(monkeypatch):
    _clear_cache()
    monkeypatch.setattr("scrum_agent.voice.is_voice_available", lambda: (True, ""))
    monkeypatch.setattr("scrum_agent.music.is_music_available", lambda: (True, ""))
    assert any("Ctrl+P" in t for t in get_tips())
    _clear_cache()


def test_music_tip_when_unavailable(monkeypatch):
    _clear_cache()
    monkeypatch.setattr("scrum_agent.voice.is_voice_available", lambda: (True, ""))
    monkeypatch.setattr("scrum_agent.music.is_music_available", lambda: (False, "no ffplay"))
    assert any("brew install" in t and "ffmpeg" in t for t in get_tips())
    _clear_cache()


def test_current_tip_advances_with_tick(monkeypatch):
    _clear_cache()
    monkeypatch.setattr("scrum_agent.voice.is_voice_available", lambda: (True, ""))
    idx0, _ = current_tip(0.0)
    idx1, _ = current_tip(TIP_ROTATE_SECONDS + 0.1)
    assert idx0 == 0
    assert idx1 == 1
    _clear_cache()


def test_current_tip_stable_within_window(monkeypatch):
    _clear_cache()
    monkeypatch.setattr("scrum_agent.voice.is_voice_available", lambda: (True, ""))
    idx_a, text_a = current_tip(0.0)
    idx_b, text_b = current_tip(TIP_ROTATE_SECONDS - 0.01)
    assert idx_a == idx_b
    assert text_a == text_b
    _clear_cache()


def test_current_tip_wraps_around(monkeypatch):
    _clear_cache()
    monkeypatch.setattr("scrum_agent.voice.is_voice_available", lambda: (True, ""))
    n = len(get_tips())
    # After a full cycle we return to the first tip.
    idx_first, _ = current_tip(0.0)
    idx_wrapped, _ = current_tip(n * TIP_ROTATE_SECONDS + 0.1)
    assert idx_first == idx_wrapped == 0
    _clear_cache()


def test_current_tip_handles_negative_tick(monkeypatch):
    _clear_cache()
    monkeypatch.setattr("scrum_agent.voice.is_voice_available", lambda: (True, ""))
    idx, text = current_tip(-5.0)
    assert idx == 0
    assert text
    _clear_cache()


def test_rotate_seconds_override(monkeypatch):
    _clear_cache()
    monkeypatch.setattr("scrum_agent.voice.is_voice_available", lambda: (True, ""))
    # With a 1s window, tick=1.5 lands on the second tip.
    idx, _ = current_tip(1.5, rotate_seconds=1.0)
    assert idx == 1
    _clear_cache()


def test_module_constant_present():
    assert _tips.TIP_ROTATE_SECONDS > 0


def test_tip_count_matches_get_tips(monkeypatch):
    _clear_cache()
    monkeypatch.setattr("scrum_agent.voice.is_voice_available", lambda: (True, ""))
    assert tip_count() == len(get_tips())
    _clear_cache()


def test_tip_brightness_full_mid_window():
    # Mid-window (well away from either edge) is fully visible.
    assert tip_brightness(TIP_ROTATE_SECONDS / 2) == 1.0


def test_tip_brightness_fades_in_at_start():
    # Just after a tip appears it is dimmer than mid-window.
    assert 0.0 <= tip_brightness(0.05) < 1.0


def test_tip_brightness_fades_out_before_switch():
    # Just before the next tip it is dimming back toward the background.
    assert 0.0 <= tip_brightness(TIP_ROTATE_SECONDS - 0.05) < 1.0


def test_tip_brightness_in_unit_range():
    for t in (0.0, 0.5, 2.9, 3.0, 5.9, 6.1, 42.0):
        b = tip_brightness(t)
        assert 0.0 <= b <= 1.0
