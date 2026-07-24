"""Tests for tips rendering in the TUI: the mode-screen banner and inline hint."""

from rich.panel import Panel

from yeaboi.ui.mode_select.screens._screens import _build_mode_screen, _build_tip_rows
from yeaboi.ui.mode_select.screens._screens_secondary import _build_all_tips_screen
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


def test_tip_rows_show_recovery_hint_when_disabled(monkeypatch):
    # Hidden tips must stay discoverable: the first row is blank (layout stays
    # stable) but the second keeps a quiet "t show tips" affordance.
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: False)
    rows = _build_tip_rows(0.0)
    assert rows[0].plain == ""
    assert "show tips" in rows[1].plain


def test_tip_rows_show_labeled_keys(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)
    text = _tip_rows_text(shimmer_tick=0.0)
    assert "prev" in text and "next" in text  # browse keys, labeled
    assert "hide" in text


def test_tip_rows_have_no_position_indicator(monkeypatch):
    # No per-tip dots and no "n/total" counter — an auto-rotating tip needs no
    # position indicator, and both grew clutter as tips were added.
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)
    monkeypatch.setattr("yeaboi.voice.is_voice_available", lambda: (True, ""))
    _tips.get_tips.cache_clear()
    total = _tips.tip_count()
    text = _tip_rows_text(shimmer_tick=0.0, tip_offset=2)
    assert "●" not in text and "○" not in text  # no dots
    assert f"/{total}" not in text  # no counter
    _tips.get_tips.cache_clear()


def test_tip_rows_open_hint_only_for_carded_tip(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)
    monkeypatch.setattr("yeaboi.voice.is_voice_available", lambda: (True, ""))
    _tips.get_tips.cache_clear()
    tips = _tips.get_tips()
    carded = next(i for i, t in enumerate(tips) if t.mode_key is not None)
    ambient = next(i for i, t in enumerate(tips) if t.mode_key is None)
    assert "open" in _tip_rows_text(shimmer_tick=0.0, tip_offset=carded)
    assert "open" not in _tip_rows_text(shimmer_tick=0.0, tip_offset=ambient)
    _tips.get_tips.cache_clear()


def test_tip_rows_new_badge_when_flagged(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)
    monkeypatch.setattr("yeaboi.voice.is_voice_available", lambda: (True, ""))
    _tips.get_tips.cache_clear()
    tips = _tips.get_tips()
    new_idx = next(i for i, t in enumerate(tips) if t.is_new)
    plain_idx = next(i for i, t in enumerate(tips) if not t.is_new)
    assert "NEW" in _tip_rows_text(shimmer_tick=0.0, tip_offset=new_idx)
    assert "NEW" not in _tip_rows_text(shimmer_tick=0.0, tip_offset=plain_idx)
    _tips.get_tips.cache_clear()


def test_tip_offset_shifts_the_shown_tip(monkeypatch):
    monkeypatch.setattr("yeaboi.config.is_tips_enabled", lambda: True)
    monkeypatch.setattr("yeaboi.voice.is_voice_available", lambda: (True, ""))
    _tips.get_tips.cache_clear()
    tips = _tips.get_tips()
    # At tick 0 the auto index is 0, so a browse offset selects tips[offset] —
    # and because it's an offset (not a pin) auto-rotation keeps advancing.
    assert tips[0].text in _tip_rows_text(shimmer_tick=0.0, tip_offset=0)
    assert tips[2].text in _tip_rows_text(shimmer_tick=0.0, tip_offset=2)
    _tips.get_tips.cache_clear()


# --- All Tips gallery page (opened with `a`) ---------------------------------


def _all_tips_rendered(**kwargs) -> str:
    import io

    from rich.console import Console

    buf = io.StringIO()
    Console(file=buf, width=100, height=30).print(_build_all_tips_screen(**kwargs))
    return buf.getvalue()


def test_all_tips_screen_renders_panel(monkeypatch):
    monkeypatch.setattr("yeaboi.voice.is_voice_available", lambda: (True, ""))
    _tips.get_tips.cache_clear()
    result = _build_all_tips_screen(shimmer_tick=0.0, sub_reveal=99, actions=["Copy all", "Back"])
    assert isinstance(result, Panel)
    _tips.get_tips.cache_clear()


def test_all_tips_screen_shows_a_tip_and_new_badge(monkeypatch):
    monkeypatch.setattr("yeaboi.voice.is_voice_available", lambda: (True, ""))
    _tips.get_tips.cache_clear()
    out = _all_tips_rendered(shimmer_tick=0.0, sub_reveal=99)
    assert "NEW" in out
    assert "opens" in out  # a carded tip's "→ opens <Mode>" note
    _tips.get_tips.cache_clear()


def test_all_tips_screen_groups_every_tip_once(monkeypatch):
    monkeypatch.setattr("yeaboi.voice.is_voice_available", lambda: (True, ""))
    monkeypatch.setattr(
        "yeaboi.ui.mode_select.screens._screens_secondary.build_scrollbar",
        lambda *_args, **_kwargs: None,
    )
    _tips.get_tips.cache_clear()
    tips = _tips.get_tips()
    out = _all_tips_rendered(height=200, shimmer_tick=0.0, sub_reveal=99)
    assert out.index("Modes") < out.index("More workflows") < out.index("Shortcuts & setup")
    content_lines = [line.strip().strip("│").strip() for line in out.splitlines()[1:-1]]
    normalized_out = " ".join(" ".join(content_lines).split())
    for tip in tips:
        _prefix, marker, display_text = tip.text.partition("Tip: ")
        expected = display_text if marker else tip.text
        assert normalized_out.count(" ".join(expected.split())) == 1
    _tips.get_tips.cache_clear()


def test_all_tips_screen_omits_terminal_unsafe_emoji_prefixes(monkeypatch):
    monkeypatch.setattr("yeaboi.voice.is_voice_available", lambda: (True, ""))
    _tips.get_tips.cache_clear()
    out = _all_tips_rendered(height=200, shimmer_tick=0.0, sub_reveal=99)
    assert "Analysis reads your board" in out
    assert "🔍" not in out
    assert "🗺️" not in out
    assert "Tip:" not in out
    _tips.get_tips.cache_clear()


def test_all_tips_screen_keeps_full_frame_at_common_widths(monkeypatch):
    import io

    from rich.cells import cell_len
    from rich.console import Console

    monkeypatch.setattr("yeaboi.voice.is_voice_available", lambda: (True, ""))
    _tips.get_tips.cache_clear()
    for width, height in ((60, 20), (80, 24), (100, 30)):
        buf = io.StringIO()
        console = Console(file=buf, width=width, height=height, color_system=None)
        console.print(
            _build_all_tips_screen(
                width=width,
                height=height,
                shimmer_tick=0.0,
                sub_reveal=99,
            )
        )
        lines = buf.getvalue().splitlines()
        assert len(lines) == height
        assert lines[0].startswith("╭") and lines[0].endswith("╮")
        assert lines[-1].startswith("╰") and lines[-1].endswith("╯")
        assert all(cell_len(line) == width for line in lines)
        assert all(line.startswith("│") and line.endswith("│") for line in lines[1:-1])
    _tips.get_tips.cache_clear()


def test_all_tips_screen_shows_status_message(monkeypatch):
    monkeypatch.setattr("yeaboi.voice.is_voice_available", lambda: (True, ""))
    _tips.get_tips.cache_clear()
    out = _all_tips_rendered(shimmer_tick=0.0, sub_reveal=99, message="Copied to clipboard")
    assert "Copied to clipboard" in out
    _tips.get_tips.cache_clear()


def test_all_tips_screen_scrolls(monkeypatch):
    # A large scroll offset is clamped and still renders a Panel (no crash).
    monkeypatch.setattr("yeaboi.voice.is_voice_available", lambda: (True, ""))
    _tips.get_tips.cache_clear()
    result = _build_all_tips_screen(scroll_offset=999, shimmer_tick=1.0, sub_reveal=99)
    assert isinstance(result, Panel)
    _tips.get_tips.cache_clear()
