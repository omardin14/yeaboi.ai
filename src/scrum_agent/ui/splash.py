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
import re
import time

import rich.box
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text

from scrum_agent.ui.shared._ascii_font import render_ascii_text
from scrum_agent.ui.shared._music_bar import make_live
from scrum_agent.ui.shared._wordmarks import get_shadow_wordmark

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
    rgb: tuple[int, int, int] = _BRAND_RGB,
) -> Panel:
    """Build a fade frame: the whole wordmark in one ``rgb`` colour at ``opacity``.

    text_lines: ASCII-art rows (a tall ANSI-Shadow wordmark, or the compact
        two-line render_ascii_text fallback). All rows must be equal width so
        per-line centre-justify keeps them aligned.
    opacity: 0.0–1.0 controls visibility. At 0 the text is invisible
        (spaces only) so it blends with any terminal background. At 1 the
        text is full ``rgb``.
    rgb: base colour (defaults to the brand blue used by the splash).
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
        r = int(rgb[0] * opacity)
        g = int(rgb[1] * opacity)
        b = int(rgb[2] * opacity)
        style = f"bold rgb({r},{g},{b})"
        for line_idx, line in enumerate(text_lines):
            rendered.append(line, style=style)
            if line_idx < len(text_lines) - 1:
                rendered.append("\n")

    return _center_in_panel(rendered, width=width, height=height, block_h=len(text_lines))


def _shine_style(pos: float, hotspot: float, rgb: tuple[int, int, int] = _BRAND_RGB) -> str:
    """Per-character style: full ``rgb``, blended towards white near the glint.

    A tight Gaussian ``hotspot`` (0–1 across the wordmark) sweeps past each
    character at normalised column ``pos``; characters near it flare white.
    """
    dist = abs(pos - hotspot)
    intensity = math.exp(-(dist * dist) / 0.012)
    r, g, b = rgb
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
    rgb: tuple[int, int, int] = _BRAND_RGB,
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
            rendered.append(ch, style=_shine_style(pos, hotspot, rgb))
        if line_idx < len(text_lines) - 1:
            rendered.append("\n")

    return _center_in_panel(rendered, width=width, height=height, block_h=len(text_lines))


def _as_rgb(color: tuple[int, int, int] | str) -> tuple[int, int, int]:
    """Coerce an ``(r,g,b)`` tuple or an ``"rgb(r,g,b)"`` string to a tuple."""
    if isinstance(color, tuple):
        return color
    nums = re.findall(r"\d+", color)
    if len(nums) >= 3:
        return (int(nums[0]), int(nums[1]), int(nums[2]))
    return _BRAND_RGB


def _resolve_wordmark(word: str, available_width: int) -> list[str]:
    """Return the tall ANSI-Shadow rows for *word* if they fit, else compact art.

    Falls back to the two-line render_ascii_text font when the terminal is too
    narrow for the baked wordmark (e.g. "Performance" on an 80-col terminal), so
    the intro never wraps into an unreadable mess.
    """
    art = get_shadow_wordmark(word)
    if art and len(art[0]) + 6 <= available_width:  # +6 for panel border + padding
        return art
    return render_ascii_text(word)


def _run_wordmark_animation(
    console: Console,
    live: object,
    text_lines: list[str],
    rgb: tuple[int, int, int],
    *,
    fade_in_frames: int,
    shine_frames: int,
    fade_out_frames: int,
    frame_time: float,
) -> None:
    """Drive ``live`` through fade-in → diagonal shine → fade-out for a wordmark.

    Shared by the brand splash and the per-mode intros. ``live`` is any object
    with an ``update(renderable)`` method (a Rich Live). Glint travels from just
    off the left edge to past the right edge so it enters and fully exits cleanly.
    """
    shine_start, shine_end = -0.25, 1.4

    # Phase 1 — Fade in: nothing → colour
    for frame in range(fade_in_frames):
        t = _ease_out_cubic(frame / max(fade_in_frames - 1, 1))
        w, h = console.size
        live.update(_build_splash_frame(text_lines, width=w, height=h, opacity=t, rgb=rgb))
        time.sleep(frame_time)

    # Phase 2 — Shine: a diagonal glint sweeps across the fully-lit wordmark
    for frame in range(shine_frames):
        t = frame / max(shine_frames - 1, 1)
        hotspot = shine_start + (shine_end - shine_start) * t
        w, h = console.size
        live.update(_build_shine_frame(text_lines, width=w, height=h, hotspot=hotspot, rgb=rgb))
        time.sleep(frame_time)

    # Phase 3 — Fade out: colour → nothing
    for frame in range(fade_out_frames):
        t = 1.0 - _ease_out_cubic(frame / max(fade_out_frames - 1, 1))
        w, h = console.size
        live.update(_build_splash_frame(text_lines, width=w, height=h, opacity=t, rgb=rgb))
        time.sleep(frame_time)


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
        _run_wordmark_animation(
            console,
            live,
            text_lines,
            _BRAND_RGB,
            fade_in_frames=48,  # ~0.8s
            shine_frames=66,  # ~1.1s
            fade_out_frames=48,  # ~0.8s
            frame_time=_FRAME_TIME,
        )

    # Alt-screen is intentionally left active — the next Live(screen=True)
    # in wizard or mode-select will take over without a visible gap.


def play_wordmark_intro(
    console: Console,
    live: object,
    word: str,
    color: tuple[int, int, int] | str,
    *,
    frame_time: float = _FRAME_TIME,
) -> None:
    """Play a snappy fade-in + shine intro for *word* on an existing ``live``.

    Used for the cinematic per-mode entrances (Planning, Retro, …): reuses the
    caller's Rich Live so there is no nested-Live flicker, renders the mode name
    as an ANSI-Shadow wordmark (falling back to the compact font when the
    terminal is too narrow), and tints it with the mode's accent ``color`` (an
    ``(r,g,b)`` tuple or ``"rgb(r,g,b)"`` string). Timing is derived from
    ``frame_time`` so it looks the same regardless of the caller's frame rate.
    """
    rgb = _as_rgb(color)
    text_lines = _resolve_wordmark(word, console.size[0])

    def _frames(seconds: float) -> int:
        if frame_time <= 0:
            return 1
        return max(1, round(seconds / frame_time))

    _run_wordmark_animation(
        console,
        live,
        text_lines,
        rgb,
        fade_in_frames=_frames(0.32),
        shine_frames=_frames(0.75),
        fade_out_frames=_frames(0.24),
        frame_time=frame_time,
    )
