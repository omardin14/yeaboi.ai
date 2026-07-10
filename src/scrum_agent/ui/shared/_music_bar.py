"""Persistent music status bar — rendered on every screen's bottom border.

# See README: "Music (cliamp)" and "TUI system" — this is the whole-app view for
# the optional background-music feature in :mod:`scrum_agent.music`.

Two chokepoints let a single, always-visible music indicator cover the entire app
without touching ~30 screen builders:

- **Render.** :class:`MusicLive` subclasses Rich's ``Live`` and, on every
  ``update``, stamps a compact status line onto the ``Panel``'s bottom **border**
  (``Panel.subtitle``). Because it edits the border rather than adding a footer
  row, no screen needs its height recomputed. Every screen already renders through
  a single ``Live`` object built at ~4 sites, so swapping those to :func:`make_live`
  is all it takes. Meaningful subtitles set by transient popups are left untouched.
- **Control** lives in ``read_key`` (Ctrl+P / Ctrl+O) — see ``_input.py``.

:func:`nudge_music_bar` lets :mod:`scrum_agent.music` force an immediate redraw
after a state change so even blocking-input screens reflect it instantly (most
screens already re-render at 30–60 fps).
"""

from __future__ import annotations

import logging

from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from scrum_agent import music
from scrum_agent.ui.shared._components import PLANNING_THEME, Theme

logger = logging.getLogger(__name__)

# The MusicLive currently rendering the app, so music.py can nudge it after a
# state change. Set on every update(); there is only ever one live screen.
_active: MusicLive | None = None


def build_music_subtitle(theme: Theme = PLANNING_THEME) -> Text:
    """Return the compact music status line for a Panel's bottom border.

    Shows the player state plus the two control-chord hints, e.g.
    ``♪ Lofi · playing   ^P pause · ^O channel``. When cliamp isn't installed it
    shows a dim, one-line install hint instead so the feature stays discoverable.
    Styled with the shared Theme palette (no hardcoded RGB), matching the rest of
    the TUI.
    """
    available, _reason = music.is_music_available()
    if not available:
        return Text("♪ music: brew install bjarneo/cliamp/cliamp ", style=theme.dim, justify="right")
    status = music.status()
    line = Text(justify="right")
    if status == "stopped":
        line.append("♪ off ", style=theme.muted)
        toggle_hint = "^P play"
    else:
        line.append("♪ ", style=theme.accent)
        line.append(music.current_channel_name(), style=theme.accent_bright)
        line.append(" · ", style=theme.muted)
        line.append("playing" if status == "playing" else "paused", style=theme.value)
        line.append("  ", style=theme.muted)
        toggle_hint = "^P pause" if status == "playing" else "^P play"
    line.append(f"  {toggle_hint} · ^O channel ", style=theme.dim)
    return line


class MusicLive(Live):
    """A Rich ``Live`` that stamps the music status onto every Panel it renders."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_renderable = None
        self._stamped = False

    def update(self, renderable, *, refresh: bool = False) -> None:
        global _active
        _active = self
        self._last_renderable = renderable
        self._stamp(renderable)
        super().update(renderable, refresh=refresh)

    def _stamp(self, renderable) -> None:
        """Set the music subtitle on a bare Panel; leave popups and non-Panels alone."""
        if not isinstance(renderable, Panel):
            self._stamped = False
            return
        # A subtitle we didn't set (a popup's own status) is meaningful — don't
        # clobber it. Our own previous stamp is tagged so we can refresh it.
        if getattr(renderable, "subtitle", None) and not getattr(renderable, "_music_stamped", False):
            self._stamped = False
            return
        # Always stamp — build_music_subtitle() renders a dim install hint when
        # cliamp is unavailable, so the bar stays present (and discoverable).
        renderable.subtitle = build_music_subtitle()
        renderable.subtitle_align = "right"
        renderable._music_stamped = True
        self._stamped = True

    def restamp(self) -> None:
        """Recompute the subtitle for the current screen and push a refresh."""
        if self._last_renderable is None:
            return
        self._stamp(self._last_renderable)
        if not self._stamped:
            return
        try:
            self.refresh()
        except Exception:  # noqa: BLE001 - refreshing a stopped Live is harmless to skip
            logger.debug("Music bar refresh skipped", exc_info=True)


def make_live(*args, **kwargs) -> MusicLive:
    """Construct the app's Live so every screen gets the persistent music bar."""
    return MusicLive(*args, **kwargs)


def nudge_music_bar() -> None:
    """Redraw the status bar immediately after a music state change."""
    if _active is not None and getattr(_active, "is_started", False):
        _active.restamp()
