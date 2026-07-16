"""Rotating discoverability tips for the welcome screen.

Single source of truth for the tip list and the (pure) rotation math. Kept out of
the screen builders so it can be unit-tested without a Rich Console and reused if
other screens want to surface a tip.

# See README: "Architecture" — pure helpers with no side effects; the screen
# builder decides how to render them.

Design notes:
- **Driven by the existing render tick.** The mode-select loop already re-renders
  at 60 FPS and threads a continuous ``shimmer_tick`` (seconds since the loop
  started) into the screen builder. :func:`current_tip` turns that float into a
  tip index with plain modulo arithmetic — no timer or background thread.
- **Availability-aware voice tip.** The first tip adapts to whether the optional
  voice extra is installed, mirroring ``_voice_hint()`` in the input screens.
- **Cached list.** Voice availability can't change during a process, so the tip
  list is memoised — this keeps the per-frame render from re-running the
  ``find_spec`` availability probe 60×/second.
"""

from __future__ import annotations

from functools import lru_cache

# Seconds each tip stays on screen before the next one rotates in.
TIP_ROTATE_SECONDS = 6.0

# General product tips shown after the voice tip. Keep them short (one line) and
# action-oriented — they render centered and dimmed under the mode list.
_GENERAL_TIPS: tuple[str, ...] = (
    "\U0001f4a1 Tip: resume your last session any time with --resume",
    "\U0001f4a1 Tip: push epics & stories straight to Jira or Azure DevOps",
    "\U0001f4a1 Tip: export a plan to HTML or JSON for sharing and CI/CD",
    "\U0001f4a1 Tip: import a filled-in questionnaire with --questionnaire",
    "\U0001f4a1 Tip: switch between --theme dark and --theme light",
    "\U0001f4a1 Tip: run headless with --non-interactive for scripts & pipelines",
)


@lru_cache(maxsize=1)
def get_tips() -> tuple[str, ...]:
    """Return the ordered tips shown on the welcome screen.

    The first entry is the voice tip and the last is the music tip; both adapt to
    whether their optional dependency is installed (dictation extra / the ffplay
    binary), showing an install hint otherwise. The middle entries are static
    product tips. Memoised because availability is fixed for the life of the
    process.
    """
    from scrum_agent.music import is_music_available
    from scrum_agent.voice import is_voice_available

    available, _reason = is_voice_available()
    voice_tip = (
        "\U0001f3a4 Tip: double-tap Space in any text field to dictate"
        if available
        else "\U0001f3a4 Tip: enable dictation with — uv sync --extra voice"
    )
    music_available, _music_reason = is_music_available()
    music_tip = (
        "\U0001f3b5 Tip: press Ctrl+P for focus music · Ctrl+O to switch channel"
        if music_available
        else "\U0001f3b5 Tip: play focus music while you plan — brew install ffmpeg"
    )
    return (voice_tip, *_GENERAL_TIPS, music_tip)


def tip_count() -> int:
    """Number of tips in rotation (used to render position dots)."""
    return len(get_tips())


def current_tip(tick: float, rotate_seconds: float = TIP_ROTATE_SECONDS) -> tuple[int, str]:
    """Return ``(index, text)`` for the tip visible at ``tick`` seconds.

    ``tick`` is the monotonic elapsed time already threaded through the render
    loop. The tip advances every ``rotate_seconds``; the index wraps around the
    tip list so rotation is continuous.
    """
    tips = get_tips()
    if not tips:  # pragma: no cover - defensive; the list is always populated
        return 0, ""
    period = rotate_seconds if rotate_seconds > 0 else TIP_ROTATE_SECONDS
    idx = int(max(0.0, tick) / period) % len(tips)
    return idx, tips[idx]


# Fraction of each rotation window spent fading in (and, symmetrically, out).
_FADE_FRACTION = 0.16


def tip_brightness(tick: float, rotate_seconds: float = TIP_ROTATE_SECONDS) -> float:
    """Return a 0..1 brightness for the current tip so it can cross-fade.

    Each tip fades up from the background over the first ``_FADE_FRACTION`` of
    its window, holds at full brightness, then fades back down over the last
    ``_FADE_FRACTION`` — so one tip dissolves out as the next dissolves in. The
    caller lerps its text/dot colours by this value. Pure and testable; no I/O.
    """
    period = rotate_seconds if rotate_seconds > 0 else TIP_ROTATE_SECONDS
    phase = (max(0.0, tick) % period) / period  # position within this tip's window, 0..1
    if phase < _FADE_FRACTION:
        return phase / _FADE_FRACTION
    if phase > 1.0 - _FADE_FRACTION:
        return max(0.0, (1.0 - phase) / _FADE_FRACTION)
    return 1.0
