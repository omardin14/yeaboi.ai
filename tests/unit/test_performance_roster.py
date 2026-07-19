"""Unit tests for the Performance roster builder (mocked Jira/AzDO helpers)."""

import yeaboi.ui.mode_select as mode_select
from yeaboi.performance import roster
from yeaboi.sessions import SessionStore


class TestFetchRoster:
    def test_distinct_assignees_merged_and_sorted(self, monkeypatch):
        monkeypatch.setattr(
            "yeaboi.tools.jira.jira_recent_activity",
            lambda project_key, days=1, **kwargs: [
                {"author": "Bob"},
                {"author": "Ada"},
                {"author": "Bob"},  # duplicate collapses
                {"author": ""},  # empty dropped
            ],
        )
        monkeypatch.setattr(
            "yeaboi.tools.azure_devops.azdevops_recent_activity",
            lambda project, days=1: [{"author": "Carol"}, {"author": "Ada"}],
        )
        result = roster.fetch_roster(jira_project="PROJ", azdo_project="AZ")
        assert [r.name for r in result] == ["Ada", "Bob", "Carol"]
        # Ada came from both — Jira (first source) wins the source tag.
        ada = next(r for r in result if r.name == "Ada")
        assert ada.source == "jira"

    def test_jira_roster_counts_assignees_only(self, monkeypatch):
        # The roster must ask Jira for assignee-credited items only — commenters
        # and changelog actors (drive-by editors) are not team-membership evidence.
        captured = {}

        def fake_activity(project_key, days=1, **kwargs):
            captured.update(kwargs)
            return [{"author": "Ada"}]

        monkeypatch.setattr("yeaboi.tools.jira.jira_recent_activity", fake_activity)
        monkeypatch.setattr("yeaboi.tools.azure_devops.azdevops_recent_activity", lambda project, days=1: [])
        result = roster.fetch_roster(jira_project="PROJ", azdo_project="AZ")
        assert [r.name for r in result] == ["Ada"]
        assert captured["include_changelog"] is False
        assert captured["include_comments"] is False

    def test_empty_when_no_projects(self, monkeypatch):
        # No projects and no env config → empty roster, no crash.
        monkeypatch.setattr("yeaboi.config.get_jira_project_key", lambda: "")
        monkeypatch.setattr("yeaboi.config.get_azure_devops_project", lambda: "")
        assert roster.fetch_roster() == []

    def test_jira_failure_is_swallowed(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("network")

        monkeypatch.setattr("yeaboi.tools.jira.jira_recent_activity", boom)
        # AzDO still contributes; Jira failure degrades to nothing.
        monkeypatch.setattr(
            "yeaboi.tools.azure_devops.azdevops_recent_activity",
            lambda project, days=1: [{"author": "Carol"}],
        )
        result = roster.fetch_roster(jira_project="PROJ", azdo_project="AZ")
        assert [r.name for r in result] == ["Carol"]


class TestSessionTeamFallback:
    def test_falls_back_to_session_team_members(self, monkeypatch, tmp_path):
        db = tmp_path / "sessions.db"
        with SessionStore(db) as s:
            s.create_session("sess-1", "Demo", mode="planning")
            s.save_state("sess-1", {"selected_team_members": ("Bob", "Ada", "Bob")})
        monkeypatch.setattr(mode_select, "_ana_dbp", db)
        # De-duplicated + sorted case-insensitively.
        assert mode_select._performance_session_team("sess-1") == ["Ada", "Bob"]

    def test_empty_when_no_team_members(self, monkeypatch, tmp_path):
        db = tmp_path / "sessions.db"
        with SessionStore(db) as s:
            s.create_session("sess-1", "Demo", mode="planning")
            s.save_state("sess-1", {})
        monkeypatch.setattr(mode_select, "_ana_dbp", db)
        assert mode_select._performance_session_team("sess-1") == []
