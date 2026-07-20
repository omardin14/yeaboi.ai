"""Tests for _standup_read_line's initial= seeding (used by the feedback form)."""

from __future__ import annotations

import io

from rich.console import Console

from yeaboi.ui.mode_select import _standup_read_line


class _FakeLive:
    def update(self, renderable):
        pass


def _console() -> Console:
    return Console(file=io.StringIO(), width=80, height=24, legacy_windows=False)


def _keys(*keys: str):
    seq = list(keys)
    return lambda **_kw: seq.pop(0)


def _read(read_key, *, initial: str = "", box_rows: int = 1):
    return _standup_read_line(
        _console(),
        _FakeLive(),
        read_key,
        0.01,
        False,
        prompt="Title",
        step="Feedback",
        box_rows=box_rows,
        initial=initial,
    )


class TestInitialSeeding:
    def test_enter_returns_initial_unchanged(self):
        assert _read(_keys("enter"), initial="draft text") == "draft text"

    def test_typing_appends_to_initial(self):
        assert _read(_keys("!", "enter"), initial="draft") == "draft!"

    def test_backspace_edits_initial(self):
        assert _read(_keys("backspace", "enter"), initial="draft") == "draf"

    def test_esc_cancels_even_with_initial(self):
        assert _read(_keys("esc"), initial="draft") is None

    def test_default_initial_is_empty(self):
        assert _read(_keys("x", "enter")) == "x"
