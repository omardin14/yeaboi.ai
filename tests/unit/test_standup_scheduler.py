"""Unit tests for the OS-native standup scheduler (launchd + crontab)."""

import plistlib
from unittest.mock import MagicMock

import pytest

from scrum_agent.standup import scheduler


class TestHelpers:
    def test_parse_time(self):
        assert scheduler._parse_time("09:50") == (9, 50)

    def test_parse_time_invalid(self):
        with pytest.raises(ValueError):
            scheduler._parse_time("9am")
        with pytest.raises(ValueError):
            scheduler._parse_time("25:00")

    def test_run_time_subtracts_lead(self):
        # Standup 10:00, 10 min lead → fire 09:50.
        assert scheduler.run_time("10:00", 10) == (9, 50)
        assert scheduler.run_time_str("10:00", 10) == "09:50"

    def test_run_time_zero_lead(self):
        assert scheduler.run_time("10:00", 0) == (10, 0)

    def test_run_time_wraps_before_midnight(self):
        # 00:05 standup with 10 min lead wraps to 23:55 the prior day.
        assert scheduler.run_time("00:05", 10) == (23, 55)

    def test_weekday_list_range(self):
        assert scheduler._weekday_list("1-5") == [1, 2, 3, 4, 5]

    def test_weekday_list_commas(self):
        assert scheduler._weekday_list("1,3,5") == [1, 3, 5]

    def test_weekday_list_empty_defaults_weekdays(self):
        assert scheduler._weekday_list("") == [1, 2, 3, 4, 5]

    def test_executable_args_shape(self, monkeypatch):
        monkeypatch.setattr(scheduler.shutil, "which", lambda name: "/usr/local/bin/scrum-agent")
        args = scheduler._executable_args("sess-1")
        assert args == [
            "/usr/local/bin/scrum-agent",
            "--standup-run",
            "--standup-interactive",
            "--standup-session",
            "sess-1",
        ]

    def test_executable_args_fallback_to_module(self, monkeypatch):
        monkeypatch.setattr(scheduler.shutil, "which", lambda name: None)
        args = scheduler._executable_args("sess-1")
        assert args[1:] == [
            "-m",
            "scrum_agent.cli",
            "--standup-run",
            "--standup-interactive",
            "--standup-session",
            "sess-1",
        ]


class TestLaunchd:
    def test_install_writes_plist_and_loads(self, monkeypatch, tmp_path):
        monkeypatch.setattr(scheduler, "_is_macos", lambda: True)
        monkeypatch.setattr(scheduler, "_is_linux", lambda: False)
        monkeypatch.setattr(scheduler, "_launch_agents_dir", lambda: tmp_path)
        monkeypatch.setattr(scheduler, "_launcher_dir", lambda: tmp_path / "launchers")
        monkeypatch.setattr(scheduler.shutil, "which", lambda name: "/bin/scrum-agent")
        run = MagicMock(return_value=MagicMock(returncode=0, stderr=""))
        monkeypatch.setattr(scheduler.subprocess, "run", run)

        msg = scheduler.install_schedule("sess-1", "10:00", "1-5")
        plist_file = tmp_path / "com.yeaboi.standup.sess-1.plist"
        assert plist_file.exists()
        with plist_file.open("rb") as fh:
            data = plistlib.load(fh)
        # Opens Terminal via osascript so the run can prompt for input.
        assert data["ProgramArguments"][0] == "/usr/bin/osascript"
        assert len(data["StartCalendarInterval"]) == 5
        assert data["StartCalendarInterval"][0]["Hour"] == 9
        assert data["StartCalendarInterval"][0]["Minute"] == 50
        # The launcher script holds the actual interactive CLI command.
        launcher = tmp_path / "launchers" / "standup-sess-1.sh"
        assert launcher.exists()
        script = launcher.read_text()
        assert "--standup-run" in script and "--standup-interactive" in script
        assert "launchd" in msg

    def test_sunday_maps_to_zero(self, monkeypatch, tmp_path):
        monkeypatch.setattr(scheduler, "_is_macos", lambda: True)
        monkeypatch.setattr(scheduler, "_launch_agents_dir", lambda: tmp_path)
        monkeypatch.setattr(scheduler, "_launcher_dir", lambda: tmp_path / "launchers")
        monkeypatch.setattr(scheduler.subprocess, "run", MagicMock(return_value=MagicMock(returncode=0, stderr="")))
        scheduler.install_schedule("s", "10:00", "7")
        with (tmp_path / "com.yeaboi.standup.s.plist").open("rb") as fh:
            data = plistlib.load(fh)
        assert data["StartCalendarInterval"][0]["Weekday"] == 0

    def test_status_and_remove(self, monkeypatch, tmp_path):
        monkeypatch.setattr(scheduler, "_is_macos", lambda: True)
        monkeypatch.setattr(scheduler, "_is_linux", lambda: False)
        monkeypatch.setattr(scheduler, "_launch_agents_dir", lambda: tmp_path)
        monkeypatch.setattr(scheduler, "_launcher_dir", lambda: tmp_path / "launchers")
        monkeypatch.setattr(scheduler.subprocess, "run", MagicMock(return_value=MagicMock(returncode=0, stderr="")))
        scheduler.install_schedule("sess-1", "10:00")
        assert scheduler.get_schedule_status("sess-1")["installed"] is True
        scheduler.remove_schedule("sess-1")
        assert scheduler.get_schedule_status("sess-1")["installed"] is False
        # Launcher script also cleaned up.
        assert not (tmp_path / "launchers" / "standup-sess-1.sh").exists()


class TestCron:
    def test_install_appends_entry(self, monkeypatch):
        monkeypatch.setattr(scheduler, "_is_macos", lambda: False)
        monkeypatch.setattr(scheduler, "_is_linux", lambda: True)
        monkeypatch.setattr(scheduler.shutil, "which", lambda name: "/bin/scrum-agent")
        monkeypatch.setattr(scheduler, "_read_crontab", lambda: ["# existing"])
        written = {}
        monkeypatch.setattr(scheduler, "_write_crontab", lambda lines: written.setdefault("lines", lines))

        msg = scheduler.install_schedule("sess-1", "10:00", "1-5")
        entry = written["lines"][-1]
        assert entry.startswith("50 9 * * 1,2,3,4,5 ")
        assert "--standup-run" in entry
        assert "# yeaboi-standup sess-1" in entry
        assert "crontab" in msg

    def test_install_replaces_existing_for_session(self, monkeypatch):
        monkeypatch.setattr(scheduler, "_is_macos", lambda: False)
        monkeypatch.setattr(scheduler, "_is_linux", lambda: True)
        monkeypatch.setattr(scheduler.shutil, "which", lambda name: "/bin/scrum-agent")
        monkeypatch.setattr(
            scheduler,
            "_read_crontab",
            lambda: ["0 8 * * 1 old # yeaboi-standup sess-1", "# unrelated"],
        )
        written = {}
        monkeypatch.setattr(scheduler, "_write_crontab", lambda lines: written.setdefault("lines", lines))
        scheduler.install_schedule("sess-1", "10:00")
        # old sess-1 entry removed, unrelated kept, one new entry added.
        lines = written["lines"]
        assert "# unrelated" in lines
        assert sum(1 for ln in lines if "sess-1" in ln) == 1
        assert lines[-1].startswith("50 9")

    def test_remove_filters_marker(self, monkeypatch):
        monkeypatch.setattr(scheduler, "_is_macos", lambda: False)
        monkeypatch.setattr(scheduler, "_is_linux", lambda: True)
        monkeypatch.setattr(
            scheduler,
            "_read_crontab",
            lambda: ["50 9 * * 1 cmd # yeaboi-standup sess-1", "# keep"],
        )
        written = {}
        monkeypatch.setattr(scheduler, "_write_crontab", lambda lines: written.setdefault("lines", lines))
        msg = scheduler.remove_schedule("sess-1")
        assert written["lines"] == ["# keep"]
        assert "Removed" in msg

    def test_remove_missing_returns_message(self, monkeypatch):
        monkeypatch.setattr(scheduler, "_is_macos", lambda: False)
        monkeypatch.setattr(scheduler, "_is_linux", lambda: True)
        monkeypatch.setattr(scheduler, "_read_crontab", lambda: ["# nothing here"])
        assert "No crontab schedule" in scheduler.remove_schedule("sess-1")


class TestUnsupportedPlatform:
    def test_install_unsupported(self, monkeypatch):
        monkeypatch.setattr(scheduler, "_is_macos", lambda: False)
        monkeypatch.setattr(scheduler, "_is_linux", lambda: False)
        msg = scheduler.install_schedule("sess-1", "10:00")
        assert "not supported" in msg

    def test_status_unsupported(self, monkeypatch):
        monkeypatch.setattr(scheduler, "_is_macos", lambda: False)
        monkeypatch.setattr(scheduler, "_is_linux", lambda: False)
        assert scheduler.get_schedule_status("sess-1") == {"platform": "unsupported", "installed": False, "path": ""}
