"""Unit tests for the shared TUI scroll helpers (yeaboi.ui.shared._scroll).

These guard the fix for the "impossible to scroll sometimes" bug: the loop's
offset must always stay clamped to what the screen builder can display, so
scrolling back up moves on the first keypress instead of burning dead presses.
"""

from __future__ import annotations

import pytest

from yeaboi.ui.shared._scroll import (
    SCROLL_KEYS,
    WHEEL_STEP,
    apply_scroll,
    clamp_scroll,
    max_scroll,
    publish_geometry,
)


class TestMaxScroll:
    def test_content_taller_than_viewport(self):
        assert max_scroll(total_lines=100, viewport_h=20) == 80

    def test_content_fits_returns_zero(self):
        assert max_scroll(total_lines=10, viewport_h=20) == 0

    def test_exact_fit_returns_zero(self):
        assert max_scroll(total_lines=20, viewport_h=20) == 0

    def test_never_negative(self):
        assert max_scroll(total_lines=0, viewport_h=5) == 0


class TestClampScroll:
    def test_clamps_to_max(self):
        assert clamp_scroll(999, total_lines=100, viewport_h=20) == 80

    def test_clamps_negative_to_zero(self):
        assert clamp_scroll(-5, total_lines=100, viewport_h=20) == 0

    def test_within_range_unchanged(self):
        assert clamp_scroll(40, total_lines=100, viewport_h=20) == 40


class TestApplyScroll:
    # max_offset=80 (e.g. 100 lines, 20-row viewport)
    MAX = 80
    VH = 20

    def test_down_moves_one_line(self):
        assert apply_scroll(0, "down", self.MAX, self.VH) == 1

    def test_up_moves_one_line(self):
        assert apply_scroll(5, "up", self.MAX, self.VH) == 4

    def test_wheel_uses_wheel_step(self):
        assert apply_scroll(0, "scroll_down", self.MAX, self.VH) == WHEEL_STEP
        assert apply_scroll(10, "scroll_up", self.MAX, self.VH) == 10 - WHEEL_STEP

    def test_up_clamps_at_top(self):
        # The dead-counter regression guard: from the top, "up" stays at 0
        # (never goes negative and never needs "catch-up" presses).
        assert apply_scroll(0, "up", self.MAX, self.VH) == 0

    def test_down_clamps_at_bottom(self):
        assert apply_scroll(self.MAX, "down", self.MAX, self.VH) == self.MAX

    def test_scroll_down_clamps_at_bottom(self):
        assert apply_scroll(self.MAX - 1, "scroll_down", self.MAX, self.VH) == self.MAX

    def test_home_jumps_to_top(self):
        assert apply_scroll(50, "home", self.MAX, self.VH) == 0

    def test_end_jumps_to_bottom(self):
        assert apply_scroll(0, "end", self.MAX, self.VH) == self.MAX

    def test_pagedown_moves_a_viewport(self):
        # Default page = viewport_h - 1 so one line of overlap is kept.
        assert apply_scroll(0, "pagedown", self.MAX, self.VH) == self.VH - 1

    def test_pageup_moves_a_viewport(self):
        assert apply_scroll(40, "pageup", self.MAX, self.VH) == 40 - (self.VH - 1)

    def test_custom_page_size(self):
        assert apply_scroll(0, "pagedown", self.MAX, self.VH, page=5) == 5

    def test_custom_wheel_step(self):
        assert apply_scroll(0, "scroll_down", self.MAX, self.VH, wheel_step=1) == 1

    def test_unknown_key_is_noop(self):
        assert apply_scroll(42, "enter", self.MAX, self.VH) == 42
        assert apply_scroll(42, "left", self.MAX, self.VH) == 42

    def test_negative_max_offset_treated_as_zero(self):
        # When content fits (max_offset would be 0/negative) every scroll stays at 0.
        assert apply_scroll(0, "down", -3, self.VH) == 0
        assert apply_scroll(5, "end", 0, self.VH) == 0

    @pytest.mark.parametrize("key", SCROLL_KEYS)
    def test_all_scroll_keys_stay_in_bounds(self, key):
        # Every recognised key, from any starting offset, lands within [0, max].
        for start in (-10, 0, 40, self.MAX, 999):
            result = apply_scroll(start, key, self.MAX, self.VH)
            assert 0 <= result <= self.MAX

    def test_scroll_down_then_up_is_responsive(self):
        # Regression: over-scroll must not inflate a hidden counter. Drive to the
        # bottom with the wheel, then a single "up" must actually move up.
        offset = 0
        for _ in range(1000):  # spam the wheel far past the end
            offset = apply_scroll(offset, "scroll_down", self.MAX, self.VH)
        assert offset == self.MAX
        assert apply_scroll(offset, "up", self.MAX, self.VH) == self.MAX - 1


class TestPublishGeometry:
    def test_populates_meta(self):
        meta: dict = {}
        publish_geometry(meta, max_offset=80, viewport_h=20)
        assert meta == {"max_offset": 80, "viewport_h": 20}

    def test_none_meta_is_noop(self):
        # Builders are also called outside scroll loops (meta=None) — must not raise.
        assert publish_geometry(None, max_offset=80, viewport_h=20) is None

    def test_negative_values_floored(self):
        meta: dict = {}
        publish_geometry(meta, max_offset=-5, viewport_h=0)
        assert meta["max_offset"] == 0
        assert meta["viewport_h"] == 1

    def test_meta_drives_apply_scroll(self):
        # The loop's real usage: builder publishes, loop clamps against it.
        meta: dict = {}
        publish_geometry(meta, max_offset=30, viewport_h=10)
        offset = apply_scroll(999, "down", meta["max_offset"], meta["viewport_h"])
        assert offset == 30


class TestCoalesceScroll:
    """coalesce_scroll drains a burst of scroll keys into one offset update."""

    def _reader(self, queue):
        # A reader that pops from `queue` when polled non-blocking; "" when empty.
        def read(timeout=None):
            return queue.pop(0) if queue else ""
        return read

    def test_applies_first_key_plus_buffered_burst(self):
        # first_key + 4 buffered scroll_downs, wheel_step 3 → 5*3 = 15, clamped to 80.
        from yeaboi.ui.shared._scroll import coalesce_scroll
        q = ["scroll_down", "scroll_down", "scroll_down", "scroll_down"]
        out = coalesce_scroll(0, "scroll_down", {"max_offset": 80, "viewport_h": 20}, self._reader(q))
        assert out == 15
        assert q == []  # whole burst consumed

    def test_stops_and_pushes_back_non_scroll_key(self):
        from yeaboi.ui.shared import _input
        from yeaboi.ui.shared._scroll import coalesce_scroll
        _input._pushback.clear()
        q = ["scroll_down", "enter"]
        out = coalesce_scroll(0, "scroll_down", {"max_offset": 80, "viewport_h": 20}, self._reader(q))
        assert out == 6  # two scroll_downs (first + one buffered) * 3
        assert _input._pushback == ["enter"]  # non-scroll key handed back
        # The next read_key() returns the pushed-back key (ignores real stdin).
        assert _input.read_key() == "enter"
        assert _input._pushback == []

    def test_stops_when_input_drained(self):
        from yeaboi.ui.shared._scroll import coalesce_scroll
        out = coalesce_scroll(10, "up", {"max_offset": 80, "viewport_h": 20}, self._reader([]))
        assert out == 9  # just the first key; nothing buffered

    def test_falls_back_to_single_apply_without_timeout_support(self):
        # A no-arg reader (like the test stubs) → TypeError → single apply, no drain.
        from yeaboi.ui.shared._scroll import coalesce_scroll
        calls = {"n": 0}
        def noarg_reader():
            calls["n"] += 1
            return "scroll_down"
        out = coalesce_scroll(0, "scroll_down", {"max_offset": 80, "viewport_h": 20}, noarg_reader)
        assert out == 3  # single wheel step
        assert calls["n"] == 0  # reader never successfully polled

    def test_boundary_burst_is_noop(self):
        # Bursting down at the bottom stays put (so the caller can skip the repaint).
        from yeaboi.ui.shared._scroll import coalesce_scroll
        q = ["scroll_down", "scroll_down"]
        out = coalesce_scroll(80, "scroll_down", {"max_offset": 80, "viewport_h": 20}, self._reader(q))
        assert out == 80


class TestCoalesceSteps:
    """coalesce_steps folds a nav burst into one net step for selection carousels."""

    DOWN = ("down", "right", "scroll_down")
    UP = ("up", "left", "scroll_up")

    def _reader(self, queue):
        def read(timeout=None):
            return queue.pop(0) if queue else ""
        return read

    def test_single_key_no_buffer(self):
        from yeaboi.ui.shared._scroll import coalesce_steps
        assert coalesce_steps("scroll_down", self._reader([]), down=self.DOWN, up=self.UP) == 1
        assert coalesce_steps("scroll_up", self._reader([]), down=self.DOWN, up=self.UP) == -1

    def test_sums_a_same_direction_burst(self):
        from yeaboi.ui.shared._scroll import coalesce_steps
        q = ["scroll_down", "scroll_down", "scroll_down"]  # + first = 4
        assert coalesce_steps("scroll_down", self._reader(q), down=self.DOWN, up=self.UP) == 4

    def test_mixed_directions_net_out(self):
        from yeaboi.ui.shared._scroll import coalesce_steps
        q = ["scroll_up", "scroll_up"]  # first down(+1) then two up(-2) = -1
        assert coalesce_steps("scroll_down", self._reader(q), down=self.DOWN, up=self.UP) == -1

    def test_pushes_back_non_nav_key(self):
        from yeaboi.ui.shared import _input
        from yeaboi.ui.shared._scroll import coalesce_steps
        _input._pushback.clear()
        q = ["scroll_down", "enter"]
        out = coalesce_steps("scroll_down", self._reader(q), down=self.DOWN, up=self.UP)
        assert out == 2
        assert _input._pushback == ["enter"]
        assert _input.read_key() == "enter"

    def test_no_timeout_reader_falls_back_to_first_key(self):
        from yeaboi.ui.shared._scroll import coalesce_steps
        assert coalesce_steps("scroll_down", lambda: "scroll_down", down=self.DOWN, up=self.UP) == 1
