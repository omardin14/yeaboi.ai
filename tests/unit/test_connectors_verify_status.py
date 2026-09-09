"""The per-connection verify store: what it remembers, and when it forgets.

The load-bearing cases are the forgetting ones. A stored "ok" that outlives the
credential it was about is exactly the bug this module exists to prevent, so
both routes back to untested — the explicit drop on a write, and the presence
drift that catches a hand-edited .env — are pinned here, as is the guarantee
that no credential value ever reaches the file.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from yeaboi.connectors import verify_status


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    path = tmp_path / "connection_status.json"
    monkeypatch.setattr("yeaboi.connectors.verify_status._store_path", lambda: path)
    verify_status.invalidate()
    yield path
    verify_status.invalidate()


class TestRecordAndRead:
    def test_an_unknown_connection_is_untested(self):
        status = verify_status.status_for("github")
        assert status.outcome == verify_status.OUTCOME_UNTESTED
        assert status.checked_at == "" and status.message == ""

    def test_a_successful_probe_is_remembered(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_live")
        verify_status.record("github", True, "GitHub verified", {"GITHUB_TOKEN": True})
        status = verify_status.status_for("github")
        assert status.outcome == verify_status.OUTCOME_OK
        assert status.message == "GitHub verified"
        assert status.checked_at  # an ISO timestamp, so a surface can word the age

    def test_a_failed_probe_is_remembered_with_its_reason(self, monkeypatch):
        monkeypatch.setenv("TAVUS_API_KEY", "dummy")
        verify_status.record("tavus", False, "Invalid Tavus API key", {"TAVUS_API_KEY": True})
        status = verify_status.status_for("tavus")
        assert status.outcome == verify_status.OUTCOME_FAILED
        assert status.message == "Invalid Tavus API key"

    def test_the_wire_row_is_exactly_three_keys(self, monkeypatch):
        monkeypatch.setenv("NOTION_TOKEN", "secret_abc")
        verify_status.record("notion", True, "Notion verified", {"NOTION_TOKEN": True})
        assert set(verify_status.to_row("notion")) == {"outcome", "message", "checked_at"}

    def test_all_statuses_covers_every_stored_row(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_live")
        monkeypatch.setenv("NOTION_TOKEN", "secret_abc")
        verify_status.record("github", True, "ok", {"GITHUB_TOKEN": True})
        verify_status.record("notion", False, "no", {"NOTION_TOKEN": True})
        assert set(verify_status.all_statuses()) == {"github", "notion"}


class TestNoCredentialIsStored:
    def test_the_file_records_presence_not_values(self, _store, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_super-secret-raw-token")
        verify_status.record("github", True, "GitHub verified", {"GITHUB_TOKEN": True})
        text = _store.read_text(encoding="utf-8")
        assert "ghp_super-secret-raw-token" not in text
        raw = json.loads(text)
        assert raw["connections"]["github"]["envs_present"] == {"GITHUB_TOKEN": True}


class TestForgetting:
    def test_editing_a_credential_drops_the_outcome(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_live")
        verify_status.record("github", True, "GitHub verified", {"GITHUB_TOKEN": True})
        verify_status.forget_for_env("GITHUB_TOKEN")
        assert verify_status.status_for("github").outcome == verify_status.OUTCOME_UNTESTED

    def test_an_unrelated_write_leaves_the_outcome_alone(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_live")
        verify_status.record("github", True, "GitHub verified", {"GITHUB_TOKEN": True})
        verify_status.forget_for_env("LOG_LEVEL")
        assert verify_status.status_for("github").outcome == verify_status.OUTCOME_OK

    def test_forget_drops_one_connection(self, monkeypatch):
        monkeypatch.setenv("NOTION_TOKEN", "secret_abc")
        verify_status.record("notion", True, "Notion verified", {"NOTION_TOKEN": True})
        verify_status.forget("notion")
        assert verify_status.status_for("notion").outcome == verify_status.OUTCOME_UNTESTED

    def test_a_credential_cleared_behind_our_back_reads_untested(self, monkeypatch):
        """The presence map is what catches a hand-edited .env."""
        monkeypatch.setenv("NOTION_TOKEN", "secret_abc")
        verify_status.record("notion", True, "Notion verified", {"NOTION_TOKEN": True})
        monkeypatch.delenv("NOTION_TOKEN")
        assert verify_status.status_for("notion").outcome == verify_status.OUTCOME_UNTESTED

    def test_a_credential_added_behind_our_back_reads_untested(self, monkeypatch):
        monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
        monkeypatch.setenv("JIRA_BASE_URL", "https://x.atlassian.net")
        verify_status.record("jira", False, "needs a token", {"JIRA_BASE_URL": True, "JIRA_API_TOKEN": False})
        monkeypatch.setenv("JIRA_API_TOKEN", "now-set")
        assert verify_status.status_for("jira").outcome == verify_status.OUTCOME_UNTESTED


class TestPresenceIsSnapshotted:
    def test_presence_reads_the_environment_now(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_live")
        monkeypatch.delenv("NOTION_TOKEN", raising=False)
        assert verify_status.presence(["GITHUB_TOKEN", "NOTION_TOKEN"]) == {
            "GITHUB_TOKEN": True,
            "NOTION_TOKEN": False,
        }

    def test_a_credential_written_during_a_probe_does_not_validate_the_old_verdict(self, monkeypatch):
        """The caller snapshots before probing, so a write mid-probe still drifts."""
        monkeypatch.delenv("NOTION_TOKEN", raising=False)
        before = verify_status.presence(["NOTION_TOKEN"])
        monkeypatch.setenv("NOTION_TOKEN", "written-while-the-probe-ran")
        verify_status.record("notion", True, "Notion verified", before)
        assert verify_status.status_for("notion").outcome == verify_status.OUTCOME_UNTESTED


class TestWriteFailures:
    def test_an_unwritable_store_does_not_break_the_probe(self, monkeypatch):
        """The probe already succeeded; losing the note must not raise."""

        def boom(*_a, **_k):
            raise OSError("read-only file system")

        monkeypatch.setattr(verify_status, "_write_or_raise", boom)
        verify_status.record("github", True, "ok", {"GITHUB_TOKEN": True})
        verify_status.forget_for_env("GITHUB_TOKEN")


class TestDamagedFile:
    def test_an_unreadable_file_is_an_empty_store(self, _store):
        _store.write_text("{not json", encoding="utf-8")
        verify_status.invalidate()
        assert verify_status.all_statuses() == {}

    def test_an_unknown_version_is_an_empty_store(self, _store):
        _store.write_text(json.dumps({"version": 99, "connections": {}}), encoding="utf-8")
        verify_status.invalidate()
        assert verify_status.all_statuses() == {}

    def test_a_damaged_file_is_read_once_rather_than_once_per_row(self, _store, monkeypatch):
        """to_row runs per connector on every catalog render; an uncached
        failure is one warning per connector, forever."""
        _store.write_text("{not json", encoding="utf-8")
        verify_status.invalidate()
        reads = {"n": 0}
        original = pathlib.Path.read_text

        def counted(self, *a, **k):
            if self.name == "connection_status.json":
                reads["n"] += 1
            return original(self, *a, **k)

        monkeypatch.setattr(pathlib.Path, "read_text", counted)
        for _ in range(5):
            verify_status.to_row("github")
        assert reads["n"] == 1

    def test_an_entry_with_a_nonsense_outcome_is_skipped(self, _store):
        payload = {"version": 1, "connections": {"github": {"outcome": "probably", "message": "", "checked_at": ""}}}
        _store.write_text(json.dumps(payload), encoding="utf-8")
        verify_status.invalidate()
        assert verify_status.status_for("github").outcome == verify_status.OUTCOME_UNTESTED
