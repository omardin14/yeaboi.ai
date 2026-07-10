"""Background music via cliamp — optional, auto-detected terminal music player.

This module lets users play focus music while planning. It shells out to
**cliamp** (https://github.com/bjarneo/cliamp), a standalone Winamp-inspired Go
terminal music player, and is modelled directly on :mod:`scrum_agent.voice`: an
optional, provider-agnostic helper that talks to an external binary.

# See README: "Music (cliamp)" — like voice input, background music does NOT go
# through the LangGraph agent or the get_llm() provider factory. It is a pure
# terminal-UX helper.

Design notes / architectural decisions:
- **Optional and auto-detected.** cliamp is a Go binary, not a Python package, so
  we never import or bundle it. :func:`is_music_available` just checks
  ``shutil.which("cliamp")`` — cheap enough to call on every screen render,
  mirroring :func:`scrum_agent.voice.is_voice_available`. If the binary is absent
  every entry point below is a graceful no-op.
- **Daemon + IPC.** cliamp exposes a headless daemon mode
  (``cliamp --daemon <url> --auto-play``) that plays without its own TUI while
  listening on a Unix socket, plus short-lived IPC commands (``cliamp pause`` /
  ``cliamp play`` / ``cliamp stop``) that control the running daemon. We keep a
  handle to the daemon subprocess; transport controls are separate one-shot runs.
- **Channels = radio streams.** cliamp can play a stream URL directly, so a
  "channel" is just an entry in :data:`CHANNELS`. Switching channel respawns the
  daemon with the next stream URL — the robust, documented way to change a radio
  station headlessly (IPC has no "load URL" verb).
- **Never raises into the TUI.** Every subprocess call is wrapped; a missing or
  broken cliamp logs a warning and leaves music off. Music must never break
  planning.
"""

from __future__ import annotations

import atexit
import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

# Built-in "channels": stable public internet-radio streams suited to focus work.
# Kept intentionally small; cliamp plays each URL directly in daemon mode.
CHANNELS: tuple[dict[str, str], ...] = (
    {"name": "Lofi", "url": "https://ice1.somafm.com/groovesalad-128-mp3"},
    {"name": "Jazz", "url": "https://ice1.somafm.com/sonicuniverse-128-mp3"},
    {"name": "Classical", "url": "https://stream.srg-ssr.ch/m/rsc_de/mp3_128"},
    {"name": "Ambient", "url": "https://ice1.somafm.com/dronezone-128-mp3"},
)

# How long to wait on a one-shot IPC control command before giving up. Kept short
# so a wedged cliamp can never stall the render loop.
_CTL_TIMEOUT = 3.0


class _State:
    """Mutable in-process music state (there is one music player per process)."""

    def __init__(self) -> None:
        # "stopped" (no audio), "playing", or "paused".
        self.status: str = "stopped"
        self.channel_idx: int = 0
        # Handle to the running ``cliamp --daemon`` subprocess, or None.
        self.daemon: subprocess.Popen | None = None
        # True while playback is suspended for a voice recording, so we only auto
        # resume music that *we* paused (not music the user paused themselves).
        self._paused_for_voice: bool = False
        self._initialised: bool = False


_state = _State()


def _init_state() -> None:
    """Load the persisted channel preference once, lazily on first use."""
    if _state._initialised:
        return
    _state._initialised = True
    try:
        from scrum_agent.config import get_music_channel

        idx = get_music_channel()
        if 0 <= idx < len(CHANNELS):
            _state.channel_idx = idx
    except Exception:  # noqa: BLE001 - config is best-effort; default channel is fine
        logger.debug("Could not load music channel preference", exc_info=True)


def is_music_available() -> tuple[bool, str]:
    """Return (available, reason) describing whether background music can be used.

    Music needs the optional ``cliamp`` binary on PATH. ``reason`` is empty when
    available, otherwise a short human-readable install hint for the UI. Mirrors
    :func:`scrum_agent.voice.is_voice_available` so callers/tests feel familiar.
    """
    if shutil.which("cliamp") is None:
        return False, "Install cliamp to enable music (brew install cliamp)"
    return True, ""


# ── Introspection (read by the status bar) ────────────────────────────────────


def status() -> str:
    """Return the current player status: "stopped", "playing", or "paused"."""
    return _state.status


def is_playing() -> bool:
    """Return True when audio is actively playing (not paused/stopped)."""
    return _state.status == "playing"


def current_channel_name() -> str:
    """Return the name of the currently selected channel."""
    _init_state()
    return CHANNELS[_state.channel_idx]["name"]


# ── Subprocess helpers ────────────────────────────────────────────────────────


def _control(*args: str) -> bool:
    """Run a one-shot ``cliamp`` IPC command (play/pause/stop). Never raises.

    Returns True on a clean exit, False on any failure. Failures are logged and
    swallowed so a broken cliamp can't disrupt the TUI.
    """
    try:
        subprocess.run(
            ["cliamp", *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=_CTL_TIMEOUT,
            check=False,
        )
        return True
    except Exception:  # noqa: BLE001 - music is best-effort; surface as a warning only
        logger.warning("cliamp control command failed: %s", " ".join(args), exc_info=True)
        return False


def _daemon_alive() -> bool:
    """Return True if the cliamp daemon subprocess is running."""
    return _state.daemon is not None and _state.daemon.poll() is None


def _stop_daemon() -> None:
    """Terminate the running cliamp daemon (if any) and clear the handle."""
    if _state.daemon is None:
        return
    try:
        if _state.daemon.poll() is None:
            _state.daemon.terminate()
            try:
                _state.daemon.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                _state.daemon.kill()
        logger.info("Music daemon stopped")
    except Exception:  # noqa: BLE001 - best-effort teardown
        logger.warning("Failed to stop music daemon", exc_info=True)
    finally:
        _state.daemon = None


def _start_channel() -> bool:
    """Spawn a fresh cliamp daemon playing the currently selected channel.

    Any existing daemon is torn down first so we never leave an orphan or play two
    streams at once. Returns True when the daemon was spawned.
    """
    _init_state()
    _stop_daemon()
    channel = CHANNELS[_state.channel_idx]
    try:
        _state.daemon = subprocess.Popen(
            ["cliamp", "--daemon", channel["url"], "--auto-play"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        _state.status = "playing"
        logger.info("Music playing channel %s", channel["name"])
        return True
    except Exception:  # noqa: BLE001 - music is best-effort
        logger.warning("Failed to start music daemon for %s", channel["name"], exc_info=True)
        _state.daemon = None
        _state.status = "stopped"
        return False


def _nudge() -> None:
    """Force an immediate redraw of the persistent status bar, if one is active."""
    try:
        from scrum_agent.ui.shared._music_bar import nudge_music_bar

        nudge_music_bar()
    except Exception:  # noqa: BLE001 - the bar is optional (e.g. headless/tests)
        logger.debug("Music bar nudge skipped", exc_info=True)


# ── Public controls (bound to Ctrl+P / Ctrl+O and voice hooks) ────────────────


def toggle() -> None:
    """Play/pause the music (Ctrl+P). Starts the current channel if stopped."""
    available, reason = is_music_available()
    if not available:
        logger.info("Music toggle ignored: %s", reason)
        return
    _init_state()
    if _state.status == "playing":
        if _control("pause"):
            _state.status = "paused"
            logger.info("Music paused")
    elif _state.status == "paused" and _daemon_alive():
        if _control("play"):
            _state.status = "playing"
            logger.info("Music resumed")
    else:
        _start_channel()
    _persist_enabled(_state.status != "stopped")
    _nudge()


def cycle_channel() -> None:
    """Switch to the next channel (Ctrl+O), wrapping around.

    If music is currently playing/paused the daemon respawns on the new stream and
    starts playing; if stopped we just remember the new selection.
    """
    available, reason = is_music_available()
    if not available:
        logger.info("Music channel switch ignored: %s", reason)
        return
    _init_state()
    _state.channel_idx = (_state.channel_idx + 1) % len(CHANNELS)
    _persist_channel(_state.channel_idx)
    logger.info("Music channel -> %s", CHANNELS[_state.channel_idx]["name"])
    if _state.status in ("playing", "paused"):
        _start_channel()
    _nudge()


def pause_for_voice() -> None:
    """Pause playback while a voice note is recorded; remember to resume it."""
    if _state.status == "playing":
        _state._paused_for_voice = _control("pause")
        if _state._paused_for_voice:
            _state.status = "paused"
            logger.info("Music paused for voice recording")


def resume_after_voice() -> None:
    """Resume playback that :func:`pause_for_voice` suspended."""
    if _state._paused_for_voice:
        _state._paused_for_voice = False
        if _daemon_alive() and _control("play"):
            _state.status = "playing"
            logger.info("Music resumed after voice recording")


def shutdown() -> None:
    """Stop the daemon on app exit. Idempotent; safe to call more than once."""
    _stop_daemon()
    _state.status = "stopped"


# Backstop so a crash or a missed cli.py finally still cleans up the daemon.
atexit.register(shutdown)


# ── Preference persistence (mirrors config.set_tips_enabled) ──────────────────


def _persist_enabled(enabled: bool) -> None:
    try:
        from scrum_agent.config import set_music_enabled

        set_music_enabled(enabled)
    except Exception:  # noqa: BLE001 - preference persistence is best-effort
        logger.debug("Could not persist music-enabled preference", exc_info=True)


def _persist_channel(idx: int) -> None:
    try:
        from scrum_agent.config import set_music_channel

        set_music_channel(idx)
    except Exception:  # noqa: BLE001 - preference persistence is best-effort
        logger.debug("Could not persist music channel preference", exc_info=True)
