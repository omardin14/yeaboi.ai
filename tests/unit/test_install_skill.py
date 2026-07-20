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


class TestBundledSkillFileSet:
    """--install-skill copytrees the whole bundled skill folder — assert its
    contents so a deleted file can't silently reappear (the MCP rewrite removed
    references/cli-and-generation.md) and the needed files always ship."""

    def _file_set(self) -> set[str]:
        import yeaboi

        skill_dir = Path(yeaboi.__file__).parent / "skills" / "scrum-planner"
        return {p.relative_to(skill_dir).as_posix() for p in skill_dir.rglob("*") if p.is_file()}

    def test_required_files_present(self):
        names = self._file_set()
        assert "SKILL.md" in names
        assert "README.md" in names
        assert "references/output-and-review.md" in names
        assert any(n.startswith("scripts/") and n.endswith(".py") for n in names)

    def test_deleted_shellout_reference_stays_gone(self):
        assert "references/cli-and-generation.md" not in self._file_set()

    def test_skill_md_is_mcp_based(self):
        import yeaboi

        body = (Path(yeaboi.__file__).parent / "skills" / "scrum-planner" / "SKILL.md").read_text()
        assert "plan_generate" in body
        assert "--non-interactive" not in body  # the old shell-out flow
