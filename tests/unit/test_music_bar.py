"""Tests for the persistent music status bar (ui/shared/_music_bar.py)."""

import pytest
from rich.panel import Panel
from rich.text import Text

from scrum_agent import music
from scrum_agent.ui.shared import _music_bar
from scrum_agent.ui.shared._music_bar import (
    _EQ_CHARS,
    MusicLive,
    _eq_bars,
    build_music_subtitle,
    make_live,
    nudge_music_bar,
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    music._state = music._State()
    music._state._initialised = True
    _music_bar._active = None
    monkeypatch.setattr(music, "is_music_available", lambda: (True, ""))
    yield
    _music_bar._active = None


# ── Subtitle content ──────────────────────────────────────────────────────────


def test_subtitle_when_stopped():
    music._state.status = "stopped"
    text = build_music_subtitle().plain
    assert "off" in text
    assert "^P play" in text
    assert "^O channel" in text


def test_subtitle_when_playing():
    music._state.status = "playing"
    music._state.channel_idx = 0
    text = build_music_subtitle().plain
    assert music.CHANNELS[0]["name"] in text
    assert "playing" in text
    assert "^P pause" in text


def test_subtitle_when_paused():
    music._state.status = "paused"
    text = build_music_subtitle().plain
    assert "paused" in text
    assert "^P play" in text


def test_eq_bars_shape():
    bars = _eq_bars(4)
    assert len(bars) == 4
    assert all(c in _EQ_CHARS for c in bars)


def test_playing_subtitle_includes_equalizer():
    music._state.status = "playing"
    text = build_music_subtitle().plain
    assert any(c in _EQ_CHARS for c in text)


# ── MusicLive stamping ────────────────────────────────────────────────────────


def test_make_live_returns_music_live():
    assert isinstance(make_live(Text("")), MusicLive)


def test_stamps_bare_panel():
    ml = make_live(Text(""))
    panel = Panel(Text("body"))
    ml._stamp(panel)
    assert panel.subtitle is not None
    assert getattr(panel, "_music_stamped", False) is True


def test_leaves_existing_subtitle_untouched():
    ml = make_live(Text(""))
    panel = Panel(Text("body"), subtitle="Board required")
    ml._stamp(panel)
    assert panel.subtitle == "Board required"  # a popup's own subtitle survives


def test_ignores_non_panel_renderables():
    ml = make_live(Text(""))
    ml._stamp(Text("plain"))  # must not raise
    assert ml._stamped is False


def test_install_hint_when_unavailable(monkeypatch):
    monkeypatch.setattr(music, "is_music_available", lambda: (False, "no cliamp"))
    text = build_music_subtitle().plain
    assert "brew install" in text and "cliamp" in text


def test_stamps_install_hint_when_unavailable(monkeypatch):
    # The bar stays present (dim install hint) even without cliamp, so the
    # feature remains discoverable.
    monkeypatch.setattr(music, "is_music_available", lambda: (False, "no cliamp"))
    ml = make_live(Text(""))
    panel = Panel(Text("body"))
    ml._stamp(panel)
    assert panel.subtitle is not None
    assert "brew install" in panel.subtitle.plain and "cliamp" in panel.subtitle.plain
    assert getattr(panel, "_music_stamped", False) is True


def test_update_registers_active_and_stamps():
    ml = make_live(Text(""))
    panel = Panel(Text("body"))
    ml.update(panel)
    assert _music_bar._active is ml
    assert panel.subtitle is not None


def test_nudge_is_safe_when_no_active_bar():
    _music_bar._active = None
    nudge_music_bar()  # must not raise
