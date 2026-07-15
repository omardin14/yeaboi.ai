"""Tests for the cliamp background-music controller (scrum_agent/music.py).

Everything is mocked at the subprocess boundary so no real ``cliamp`` binary,
audio device, or config file is touched. The controller must never raise into the
TUI, so failure paths are asserted to degrade quietly.
"""

import pytest

from scrum_agent import music


class _FakePopen:
    def __init__(self, args):
        self.args = args
        self._alive = True
        self.terminated = False
        self.killed = False
        self.returncode = None

    def poll(self):
        return None if self._alive else self.returncode

    def terminate(self):
        self.terminated = True
        self._alive = False
        self.returncode = 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True
        self._alive = False
        self.returncode = 0

    def die(self, code=1):
        """Simulate cliamp exiting on its own (e.g. a missing shared library)."""
        self._alive = False
        self.returncode = code


@pytest.fixture
def mock_music(monkeypatch):
    """Reset state and mock cliamp so it 'exists' and every call succeeds."""
    music._state = music._State()
    music._state._initialised = True  # skip config load; use default channel 0
    calls = {"run": [], "popen": []}

    def fake_run(args, **kwargs):
        calls["run"].append(args)

        class _Result:
            returncode = 0

        return _Result()

    def fake_popen(args, **kwargs):
        calls["popen"].append(args)
        return _FakePopen(args)

    monkeypatch.setattr(music.subprocess, "run", fake_run)
    monkeypatch.setattr(music.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(music.shutil, "which", lambda name: "/usr/bin/cliamp")
    monkeypatch.setattr(music, "_nudge", lambda: None)
    monkeypatch.setattr(music, "_persist_enabled", lambda enabled: None)
    monkeypatch.setattr(music, "_persist_channel", lambda idx: None)
    return calls


# ── Availability ──────────────────────────────────────────────────────────────


def test_available_when_binary_present(monkeypatch):
    monkeypatch.setattr(music.shutil, "which", lambda name: "/usr/bin/cliamp")
    ok, reason = music.is_music_available()
    assert ok is True
    assert reason == ""


def test_unavailable_when_binary_missing(monkeypatch):
    monkeypatch.setattr(music.shutil, "which", lambda name: None)
    ok, reason = music.is_music_available()
    assert ok is False
    assert reason  # a human-readable install hint


def test_unavailable_toggle_is_noop(monkeypatch):
    music._state = music._State()
    music._state._initialised = True
    monkeypatch.setattr(music.shutil, "which", lambda name: None)
    music.toggle()
    assert music.status() == "stopped"


# ── Toggle state machine ──────────────────────────────────────────────────────


def test_toggle_starts_when_stopped(mock_music):
    music.toggle()
    assert music.status() == "playing"
    assert mock_music["popen"], "a daemon should be spawned"
    args = mock_music["popen"][0]
    assert args[0] == "cliamp" and "--daemon" in args and "--auto-play" in args


def test_toggle_pauses_when_playing(mock_music):
    music.toggle()  # stopped -> playing
    music.toggle()  # playing -> paused
    assert music.status() == "paused"
    assert ["cliamp", "pause"] in mock_music["run"]


def test_toggle_resumes_when_paused(mock_music):
    music.toggle()  # -> playing
    music.toggle()  # -> paused
    music.toggle()  # -> playing
    assert music.status() == "playing"
    assert ["cliamp", "play"] in mock_music["run"]


# ── Channel switching ─────────────────────────────────────────────────────────


def test_cycle_channel_wraps_when_stopped(mock_music):
    music._state.channel_idx = len(music.CHANNELS) - 1
    music.cycle_channel()
    assert music._state.channel_idx == 0
    assert music.status() == "stopped"
    assert not mock_music["popen"], "stopped music should not start on channel switch"


def test_cycle_channel_respawns_when_playing(mock_music):
    music.toggle()  # playing, one daemon spawned
    name_before = music.current_channel_name()
    music.cycle_channel()
    assert music.status() == "playing"
    assert len(mock_music["popen"]) == 2, "daemon respawns on the new stream"
    assert music.current_channel_name() != name_before


def test_current_channel_name_matches_index(mock_music):
    music._state.channel_idx = 1
    assert music.current_channel_name() == music.CHANNELS[1]["name"]


# ── Voice ducking ─────────────────────────────────────────────────────────────


def test_pause_and_resume_for_voice(mock_music):
    music.toggle()  # playing
    music.pause_for_voice()
    assert music.status() == "paused"
    music.resume_after_voice()
    assert music.status() == "playing"


def test_voice_hooks_noop_when_stopped(mock_music):
    music.pause_for_voice()
    music.resume_after_voice()
    assert music.status() == "stopped"
    assert not mock_music["run"], "nothing to pause/resume when stopped"


def test_resume_only_resumes_music_we_paused(mock_music):
    # User manually paused (not for voice) → resume_after_voice must not un-pause it.
    music.toggle()  # playing
    music.toggle()  # user pauses -> paused
    music.resume_after_voice()
    assert music.status() == "paused"


# ── Robustness ────────────────────────────────────────────────────────────────


def test_control_failure_is_graceful(mock_music, monkeypatch):
    music.toggle()  # playing

    def boom(*args, **kwargs):
        raise OSError("cliamp exploded")

    monkeypatch.setattr(music.subprocess, "run", boom)
    music.toggle()  # attempts pause; run raises -> _control returns False, no raise
    assert music.status() == "playing"  # pause didn't take, but the app survives


def test_shutdown_terminates_daemon(mock_music):
    music.toggle()
    daemon = music._state.daemon
    music.shutdown()
    assert daemon.terminated
    assert music._state.daemon is None
    assert music.status() == "stopped"


# ── Daemon liveness reconciliation (crash detection) ──────────────────────────


def test_crashed_daemon_reverts_to_stopped(mock_music):
    music.toggle()  # playing
    music._state.daemon.die()  # cliamp exits on its own (e.g. missing dylib)
    # status() reconciles: the phantom "playing" collapses to a truthful "stopped".
    assert music.status() == "stopped"
    assert music.is_playing() is False
    assert music._state.daemon is None


def test_crashed_daemon_sets_last_error(mock_music):
    assert music.last_error() == ""  # clean to start
    music.toggle()  # playing
    music._state.daemon.die()
    music.status()  # triggers reconciliation
    assert "cliamp" in music.last_error()


def test_last_error_cleared_on_successful_restart(mock_music):
    music.toggle()
    music._state.daemon.die()
    music.status()  # records the crash notice
    assert music.last_error()
    music.toggle()  # stopped -> playing again (daemon respawns cleanly)
    assert music.status() == "playing"
    assert music.last_error() == ""


def test_live_daemon_is_not_reconciled(mock_music):
    music.toggle()  # playing, daemon alive
    assert music.status() == "playing"  # a healthy daemon stays playing
    assert music.last_error() == ""


def test_crashed_daemon_while_paused_reverts(mock_music):
    music.toggle()  # playing
    music.toggle()  # paused (daemon still alive)
    music._state.daemon.die()
    assert music.status() == "stopped"
    assert music.last_error()
