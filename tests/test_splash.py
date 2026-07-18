"""Tests for the startup splash animation.

Covers frame rendering at various opacity states and verifies
the full show_splash() animation runs to completion with mocked Live.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from rich.panel import Panel

from yeaboi.ui.shared._ascii_font import render_ascii_text
from yeaboi.ui.splash import _build_shine_frame, _build_splash_frame, show_splash


class TestBuildSplashFrame:
    """Tests for _build_splash_frame rendering."""

    def test_returns_panel(self):
        """Frame builder returns a Rich Panel."""
        lines = render_ascii_text("YEABOI")
        frame = _build_splash_frame(lines, width=80, height=24)
        assert isinstance(frame, Panel)

    def test_full_opacity_brand_blue(self):
        """At opacity=1.0, the brand blue colour appears in the rendered output."""
        lines = render_ascii_text("YEABOI")
        frame = _build_splash_frame(lines, width=80, height=24, opacity=1.0)
        assert isinstance(frame, Panel)
        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=80, color_system="truecolor")
        console.print(frame)
        output = buf.getvalue()
        # Brand blue (70,100,180) should appear in escape codes
        assert "70" in output and "100" in output and "180" in output

    def test_zero_opacity_invisible(self):
        """At opacity=0, text chars are replaced with spaces — nothing visible."""
        lines = render_ascii_text("TEST")
        frame = _build_splash_frame(lines, width=80, height=24, opacity=0.0)
        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=80, color_system="truecolor")
        console.print(frame)
        output = buf.getvalue()
        # No brand blue and no block characters should appear
        assert "rgb(70,100,180)" not in output
        assert "█" not in output

    def test_empty_text(self):
        """Empty text lines produce a valid panel without errors."""
        frame = _build_splash_frame(["", ""], width=80, height=24)
        assert isinstance(frame, Panel)

    def test_text_centered(self):
        """The wordmark block is horizontally centred inside the panel."""
        lines = render_ascii_text("HI")
        frame = _build_splash_frame(lines, width=80, height=24, opacity=1.0)
        art_rows = _rendered_art_rows(frame, width=80)
        block_w = max(len(line) for line in lines)
        # Panel border (1) + padding (2) + shared block pad ((inner - block)//2)
        expected_start = 3 + (74 - block_w) // 2
        assert art_rows
        assert all(_first_ink(row) == expected_start for row in art_rows)

    def test_rows_stay_aligned_with_uneven_trailing_content(self):
        """Rows whose stripped widths differ must share one left origin.

        Regression: Rich's per-line center-justify rstripped each row and
        re-centred it by its own width, so STANDUP's shorter bottom rows (the
        P glyph ends 5 cells early) drifted right and broke the letters.
        """
        from yeaboi.ui.shared._wordmarks import get_shadow_wordmark

        lines = get_shadow_wordmark("Standup")
        assert lines, "STANDUP wordmark should exist"
        frame = _build_splash_frame(lines, width=120, height=30, opacity=1.0)
        art_rows = _rendered_art_rows(frame, width=120)
        starts = {_first_ink(row) for row in art_rows}
        assert len(art_rows) == len(lines)
        assert len(starts) == 1, f"rows start at differing columns: {starts}"

    def test_shine_frame_rows_stay_aligned(self):
        """The shine frame keeps uneven rows column-aligned too."""
        from yeaboi.ui.shared._wordmarks import get_shadow_wordmark

        lines = get_shadow_wordmark("Standup")
        frame = _build_shine_frame(lines, width=120, height=30, hotspot=0.5)
        art_rows = _rendered_art_rows(frame, width=120)
        starts = {_first_ink(row) for row in art_rows}
        assert len(art_rows) == len(lines)
        assert len(starts) == 1, f"rows start at differing columns: {starts}"


_ART_CHARS = "█╗╔╝╚═║"


def _rendered_art_rows(frame, *, width: int) -> list[str]:
    """Render a frame panel to plain text and return the wordmark rows."""
    from io import StringIO

    from rich.console import Console

    buf = StringIO()
    console = Console(file=buf, width=width, height=60)
    console.print(frame)
    return [row for row in buf.getvalue().splitlines() if any(ch in _ART_CHARS for ch in row)]


def _first_ink(row: str) -> int:
    """Column of the first wordmark character in a rendered panel row."""
    return min(row.index(ch) for ch in _ART_CHARS if ch in row)


class TestShowSplash:
    """Tests for the full show_splash() animation."""

    @patch("yeaboi.ui.splash.time.sleep")
    @patch("yeaboi.ui.splash.Live")
    def test_completes_without_error(self, mock_live_cls, mock_sleep):
        """show_splash runs the full animation loop and exits cleanly."""
        # The splash uses a plain Live (not the MusicLive from make_live) so the
        # persistent music bar is never stamped onto the intro's border.
        mock_live = MagicMock()
        mock_live.__enter__ = MagicMock(return_value=mock_live)
        mock_live.__exit__ = MagicMock(return_value=False)
        mock_live_cls.return_value = mock_live

        console = MagicMock()
        console.size = (80, 24)

        show_splash(console)

        mock_live.__enter__.assert_called_once()
        mock_live.__exit__.assert_called_once()
        assert mock_live.update.call_count > 0

    def test_uses_plain_live_not_music_live(self):
        """The splash must use a plain Live, not MusicLive.

        MusicLive stamps the persistent music bar (^P/^O controls) onto every
        Panel's border. Those controls belong to the interactive screens, so the
        bar should first appear on the mode-select menu — never on the intro. If
        the splash ever switches back to make_live/MusicLive, the bar reappears
        on the animation border; this guards against that regression.
        """
        from rich.live import Live as RichLive

        from yeaboi.ui import splash as splash_mod
        from yeaboi.ui.shared._music_bar import MusicLive

        assert splash_mod.Live is RichLive
        assert not issubclass(splash_mod.Live, MusicLive)
