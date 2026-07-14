"""Startup splash animation — "YEABOI" fades in then out.

# See README: "Architecture" — the splash is a CLI-layer component shown
# before the setup wizard or mode selection screen. It replaces the static
# welcome panel as the first branded intro users see.

Animation sequence (~2.7s total):
  Phase 1 — Fade in:  text appears from nothing → brand blue (~0.8s).
  Phase 2 — Shine:    a diagonal white glint sweeps across the wordmark (~1.1s).
  Phase 3 — Fade out: brand blue → nothing (~0.8s).
"""

from __future__ import annotations

import math
import time

import rich.box
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text

from scrum_agent.ui.shared._ascii_font import render_ascii_text
from scrum_agent.ui.shared._music_bar import make_live

# ---------------------------------------------------------------------------
# Animation constants
# ---------------------------------------------------------------------------

_FRAME_TIME = 1.0 / 60  # ~60fps target

# Brand blue — same as mode_select._COLOR_RGB
_BRAND_RGB = (70, 100, 180)

# Brand wordmark — "YEABOI" in the ANSI Shadow figlet style (6 rows, all padded
# to the same width so Rich's per-line centre-justify keeps them aligned). This
# is a fixed hand-baked asset (no figlet/pyfiglet runtime dependency); the
# compact two-line render_ascii_text() font is still used for mode titles.
_WORDMARK: list[str] = [
    "██╗   ██╗███████╗ █████╗ ██████╗  ██████╗ ██╗",
    "╚██╗ ██╔╝██╔════╝██╔══██╗██╔══██╗██╔═══██╗██║",
    " ╚████╔╝ █████╗  ███████║██████╔╝██║   ██║██║",
    "  ╚██╔╝  ██╔══╝  ██╔══██║██╔══██╗██║   ██║██║",
    "   ██║   ███████╗██║  ██║██████╔╝╚██████╔╝██║",
    "   ╚═╝   ╚══════╝╚═╝  ╚═╝╚═════╝  ╚═════╝ ╚═╝",
]
_WORDMARK_WIDTH = 45  # cell width of every row above

# How far each successive wordmark row is nudged ahead of the one above it,
# so the shine reads as a slanted streak of light rather than a vertical bar.
_SHINE_ROW_SKEW = 0.03


# ---------------------------------------------------------------------------
# Easing
# ---------------------------------------------------------------------------


def _ease_out_cubic(t: float) -> float:
    """Cubic ease-out: fast start, smooth deceleration."""
    return 1 - (1 - t) ** 3


# ---------------------------------------------------------------------------
# Frame builder
# ---------------------------------------------------------------------------


def _center_in_panel(rendered: Text, *, width: int, height: int, block_h: int) -> Panel:
    """Vertically centre a pre-built ``rendered`` Text block inside the panel."""
    inner_h = height - 4  # panel border + padding
    top_pad = max(0, (inner_h - block_h) // 2)
    bot_pad = max(0, inner_h - block_h - top_pad)

    content = Group(
        *[Text("") for _ in range(top_pad)],
        rendered,
        *[Text("") for _ in range(bot_pad)],
    )

    return Panel(
        content,
        border_style="white",
        box=rich.box.ROUNDED,
        expand=True,
        height=height,
        padding=(1, 2),
    )


def _build_splash_frame(
    text_lines: list[str],
    *,
    width: int,
    height: int,
    opacity: float = 1.0,
) -> Panel:
    """Build a fade frame: the whole wordmark in one brand-blue at ``opacity``.

    text_lines: ASCII-art rows (the tall _WORDMARK, or the compact two-line
        render_ascii_text fallback). All rows must be equal width so per-line
        centre-justify keeps them aligned.
    opacity: 0.0–1.0 controls visibility. At 0 the text is invisible
        (spaces only) so it blends with any terminal background. At 1 the
        text is full brand-blue.
    """
    rendered = Text(justify="center")
    if opacity < 0.01:
        # At very low opacity, replace characters with spaces so nothing is
        # visible — avoids a near-black colour standing out against the
        # terminal background regardless of its colour scheme.
        for line_idx, line in enumerate(text_lines):
            rendered.append(" " * len(line))
            if line_idx < len(text_lines) - 1:
                rendered.append("\n")
    else:
        r = int(_BRAND_RGB[0] * opacity)
        g = int(_BRAND_RGB[1] * opacity)
        b = int(_BRAND_RGB[2] * opacity)
        style = f"bold rgb({r},{g},{b})"
        for line_idx, line in enumerate(text_lines):
            rendered.append(line, style=style)
            if line_idx < len(text_lines) - 1:
                rendered.append("\n")

    return _center_in_panel(rendered, width=width, height=height, block_h=len(text_lines))


def _shine_style(pos: float, hotspot: float) -> str:
    """Per-character style: full brand-blue, blended towards white near the glint.

    A tight Gaussian ``hotspot`` (0–1 across the wordmark) sweeps past each
    character at normalised column ``pos``; characters near it flare white.
    """
    dist = abs(pos - hotspot)
    intensity = math.exp(-(dist * dist) / 0.012)
    r, g, b = _BRAND_RGB
    r2 = int(r + (255 - r) * intensity)
    g2 = int(g + (255 - g) * intensity)
    b2 = int(b + (255 - b) * intensity)
    return f"bold rgb({r2},{g2},{b2})"


def _build_shine_frame(
    text_lines: list[str],
    *,
    width: int,
    height: int,
    hotspot: float,
) -> Panel:
    """Build a shine frame: the fully-lit wordmark with a diagonal glint sweeping.

    ``hotspot`` travels roughly -0.2 → 1.2 so the highlight enters from the left,
    crosses the letters, and exits right. Each lower row is nudged slightly ahead
    (``_SHINE_ROW_SKEW``) so the highlight reads as a slanted streak of light.
    """
    span = max(len(line) for line in text_lines) - 1 or 1
    rendered = Text(justify="center")
    for line_idx, line in enumerate(text_lines):
        for col, ch in enumerate(line):
            if ch == " ":
                rendered.append(" ")
                continue
            pos = col / span + line_idx * _SHINE_ROW_SKEW
            rendered.append(ch, style=_shine_style(pos, hotspot))
        if line_idx < len(text_lines) - 1:
            rendered.append("\n")

    return _center_in_panel(rendered, width=width, height=height, block_h=len(text_lines))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def show_splash(console: Console) -> None:
    """Show the startup splash animation (~2s). Non-interactive, timed.

    # See README: "Architecture" — this replaces _build_welcome_panel() as
    # the first thing users see. "YEABOI" fades in from nothing, a diagonal
    # glint sweeps across it, then it fades back out to nothing.

    Alt-screen management: we enter the alternate screen buffer manually
    before starting the animation and intentionally leave it active when
    the splash ends. The next fullscreen UI (setup wizard or mode-select)
    uses Live(screen=True) which re-enters alt-screen seamlessly. This
    avoids the visible flicker that would occur if the splash exited
    alt-screen and the next UI immediately re-entered it.
    """
    w, h = console.size
    # Use the tall ANSI-Shadow wordmark when the terminal is wide enough;
    # fall back to the compact two-line font on narrow terminals so it never
    # wraps into an unreadable mess.
    if w >= _WORDMARK_WIDTH + 6:  # +6 for panel border + padding
        text_lines = _WORDMARK
    else:
        text_lines = render_ascii_text("YEABOI")

    # Phase durations (in frames at ~60fps)
    fade_in_frames = 48  # ~0.8s
    shine_frames = 66  # ~1.1s — one diagonal glint sweep
    fade_out_frames = 48  # ~0.8s

    # Glint travels from just off the left edge to past the right edge (plus the
    # per-row skew) so it enters and fully exits the wordmark cleanly.
    shine_start = -0.25
    shine_end = 1.4

    # Enter alt-screen once — stays active through to the next fullscreen UI.
    # Live is created without screen=True so it doesn't toggle alt-screen
    # on enter/exit, eliminating the flicker between screens.
    console.set_alt_screen(True)
    console.clear()

    with make_live(
        _build_splash_frame(text_lines, width=w, height=h, opacity=0.0),
        console=console,
        refresh_per_second=60,
        screen=False,
    ) as live:
        # Phase 1 — Fade in: nothing → brand blue
        for frame in range(fade_in_frames):
            t = _ease_out_cubic(frame / max(fade_in_frames - 1, 1))
            w, h = console.size
            live.update(_build_splash_frame(text_lines, width=w, height=h, opacity=t))
            time.sleep(_FRAME_TIME)

        # Phase 2 — Shine: a diagonal glint sweeps across the fully-lit wordmark
        for frame in range(shine_frames):
            t = frame / max(shine_frames - 1, 1)
            hotspot = shine_start + (shine_end - shine_start) * t
            w, h = console.size
            live.update(_build_shine_frame(text_lines, width=w, height=h, hotspot=hotspot))
            time.sleep(_FRAME_TIME)

        # Phase 3 — Fade out: brand blue → nothing
        for frame in range(fade_out_frames):
            t = 1.0 - _ease_out_cubic(frame / max(fade_out_frames - 1, 1))
            w, h = console.size
            live.update(_build_splash_frame(text_lines, width=w, height=h, opacity=t))
            time.sleep(_FRAME_TIME)

    # Alt-screen is intentionally left active — the next Live(screen=True)
    # in wizard or mode-select will take over without a visible gap.
