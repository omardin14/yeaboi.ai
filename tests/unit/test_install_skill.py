"""Unit tests for the --install-skill privileged-overwrite guard (F6)."""

from pathlib import Path

import pytest

from yeaboi.cli import _confirm_sudo_overwrite, _is_dangerous_sudo_target


class TestIsDangerousSudoTarget:
    def test_filesystem_root_is_dangerous(self):
        assert _is_dangerous_sudo_target(Path("/")) is True

    def test_home_directory_is_dangerous(self):
        assert _is_dangerous_sudo_target(Path.home()) is True

    def test_normal_skill_path_is_safe(self, tmp_path):
        assert _is_dangerous_sudo_target(tmp_path / "openclaw" / "skills" / "scrum-planner") is False


class TestConfirmSudoOverwrite:
    def test_dangerous_target_refused_without_prompting(self, monkeypatch, capsys):
        # input() must never be reached for a protected path.
        monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("should not prompt"))
        assert _confirm_sudo_overwrite(Path.home()) is False
        assert "Refusing" in capsys.readouterr().err

    def test_yes_confirms(self, monkeypatch, tmp_path):
        monkeypatch.setattr("builtins.input", lambda *a: "y")
        assert _confirm_sudo_overwrite(tmp_path / "skills") is True

    def test_no_declines(self, monkeypatch, tmp_path):
        monkeypatch.setattr("builtins.input", lambda *a: "")
        assert _confirm_sudo_overwrite(tmp_path / "skills") is False

    def test_eof_declines(self, monkeypatch, tmp_path):
        def _boom(*a):
            raise EOFError

        monkeypatch.setattr("builtins.input", _boom)
        assert _confirm_sudo_overwrite(tmp_path / "skills") is False
