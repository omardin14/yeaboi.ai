"""Unit tests for the recent-activity helpers used by the Daily Standup collector.

Each source degrades gracefully to [] when unconfigured or on error, and
normalizes into the shared {author, kind, title, timestamp, key} shape.
"""

import subprocess
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scrum_agent.tools.azure_devops import azdevops_recent_activity
from scrum_agent.tools.confluence import confluence_recent_pages
from scrum_agent.tools.github import github_recent_commits, github_recent_prs
from scrum_agent.tools.jira import jira_recent_activity
from scrum_agent.tools.local_git import local_git_recent_commits


class TestJiraRecentActivity:
    def test_missing_config_returns_empty(self, monkeypatch):
        monkeypatch.setattr("scrum_agent.tools.jira._make_jira_client", lambda: None)
        assert jira_recent_activity("PROJ", days=1) == []

    def test_normalizes_issues(self, monkeypatch):
        issue = MagicMock()
        issue.key = "PROJ-12"
        issue.fields = SimpleNamespace(
            summary="Fix login",
            assignee=SimpleNamespace(displayName="Alice"),
            status=SimpleNamespace(name="In Progress"),
            updated="2026-07-10T09:00:00.000+0000",
        )
        client = MagicMock()
        client.search_issues.return_value = [issue]
        monkeypatch.setattr("scrum_agent.tools.jira._make_jira_client", lambda: client)
        monkeypatch.setattr("scrum_agent.tools.jira.get_jira_project_key", lambda: "PROJ")

        items = jira_recent_activity("PROJ", days=2)
        assert items == [
            {
                "author": "Alice",
                "kind": "issue",
                "title": "Fix login",
                "status": "In Progress",
                "timestamp": "2026-07-10T09:00:00",
                "key": "PROJ-12",
            }
        ]

    def test_api_error_returns_empty(self, monkeypatch):
        from jira import JIRAError

        client = MagicMock()
        client.search_issues.side_effect = JIRAError(status_code=500, text="boom")
        monkeypatch.setattr("scrum_agent.tools.jira._make_jira_client", lambda: client)
        monkeypatch.setattr("scrum_agent.tools.jira.get_jira_project_key", lambda: "PROJ")
        assert jira_recent_activity("PROJ") == []

    def test_auth_error_raises_source_error(self, monkeypatch):
        from jira import JIRAError

        from scrum_agent.standup.errors import StandupSourceError

        client = MagicMock()
        client.search_issues.side_effect = JIRAError(status_code=401, text="unauthorized")
        monkeypatch.setattr("scrum_agent.tools.jira._make_jira_client", lambda: client)
        monkeypatch.setattr("scrum_agent.tools.jira.get_jira_project_key", lambda: "PROJ")
        with pytest.raises(StandupSourceError) as exc:
            jira_recent_activity("PROJ")
        assert exc.value.source == "jira"


class TestGithubRecentActivity:
    def test_commits_normalized(self, monkeypatch):
        commit_obj = SimpleNamespace(
            sha="abcdef1234",
            commit=SimpleNamespace(
                author=SimpleNamespace(name="Bob", date=datetime(2026, 7, 10, 8, 0, tzinfo=UTC)),
                message="Add feature\n\nbody",
            ),
        )
        repo = MagicMock()
        repo.get_commits.return_value = [commit_obj]
        client = MagicMock()
        client.get_repo.return_value = repo
        monkeypatch.setattr("scrum_agent.tools.github._get_github_client", lambda: client)

        items = github_recent_commits("owner/repo", days=1)
        assert items[0]["author"] == "Bob"
        assert items[0]["kind"] == "commit"
        assert items[0]["title"] == "Add feature"
        assert items[0]["key"] == "abcdef12"

    def test_commits_error_returns_empty(self, monkeypatch):
        client = MagicMock()
        client.get_repo.side_effect = RuntimeError("nope")
        monkeypatch.setattr("scrum_agent.tools.github._get_github_client", lambda: client)
        assert github_recent_commits("owner/repo") == []

    def test_prs_normalized_and_merged_status(self, monkeypatch):
        pr = SimpleNamespace(
            number=42,
            title="Refactor",
            merged=True,
            state="closed",
            user=SimpleNamespace(login="carol"),
            # Relative to now so the PR always falls inside the days=1 window —
            # a fixed date made this test fail once the clock passed it.
            updated_at=datetime.now(UTC) - timedelta(hours=1),
        )
        repo = MagicMock()
        repo.get_pulls.return_value = [pr]
        client = MagicMock()
        client.get_repo.return_value = repo
        monkeypatch.setattr("scrum_agent.tools.github._get_github_client", lambda: client)

        items = github_recent_prs("owner/repo", days=1)
        assert items[0]["status"] == "merged"
        assert items[0]["key"] == "#42"
        assert items[0]["author"] == "carol"


class TestAzdoRecentActivity:
    def test_no_project_returns_empty(self, monkeypatch):
        monkeypatch.setattr("scrum_agent.tools.azure_devops.get_azure_devops_project", lambda: None)
        assert azdevops_recent_activity("", days=1) == []

    def test_normalizes_work_items(self, monkeypatch):
        wit = MagicMock()
        wit.query_by_wiql.return_value = SimpleNamespace(work_items=[SimpleNamespace(id=7)])
        item = SimpleNamespace(
            fields={
                "System.Id": 7,
                "System.Title": "Build API",
                "System.State": "Active",
                "System.AssignedTo": {"displayName": "Dana"},
                "System.ChangedDate": "2026-07-10T06:00:00Z",
            }
        )
        wit.get_work_items.return_value = [item]
        monkeypatch.setattr("scrum_agent.tools.azure_devops._make_azdo_clients", lambda: (wit, MagicMock()))

        items = azdevops_recent_activity("Proj", days=1)
        assert items[0]["author"] == "Dana"
        assert items[0]["kind"] == "work_item"
        assert items[0]["key"] == "#7"
        assert items[0]["status"] == "Active"


class TestConfluenceRecentPages:
    def test_missing_config_returns_empty(self, monkeypatch):
        monkeypatch.setattr("scrum_agent.tools.confluence._make_confluence_client", lambda: None)
        assert confluence_recent_pages("SPACE", days=1) == []

    def test_normalizes_pages(self, monkeypatch):
        conf = MagicMock()
        conf.cql.return_value = {
            "results": [
                {
                    "content": {
                        "id": "123",
                        "title": "Runbook",
                        "history": {"lastUpdated": {"by": {"displayName": "Eve"}, "when": "2026-07-10T05:00:00.000Z"}},
                    }
                }
            ]
        }
        monkeypatch.setattr("scrum_agent.tools.confluence._make_confluence_client", lambda: conf)
        monkeypatch.setattr("scrum_agent.tools.confluence.get_confluence_space_key", lambda: "SPACE")

        items = confluence_recent_pages("SPACE", days=1)
        assert items[0]["author"] == "Eve"
        assert items[0]["kind"] == "page"
        assert items[0]["title"] == "Runbook"
        assert items[0]["key"] == "123"


class TestLocalGitRecentCommits:
    def test_reads_real_repo(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()

        def git(*args):
            subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

        git("init", "-q")
        git("config", "user.email", "dev@example.com")
        git("config", "user.name", "Dev Person")
        (repo / "a.txt").write_text("hi")
        git("add", ".")
        git("commit", "-q", "-m", "first commit")

        items = local_git_recent_commits(str(repo), days=1)
        assert len(items) == 1
        assert items[0]["author"] == "Dev Person"
        assert items[0]["title"] == "first commit"
        assert items[0]["kind"] == "commit"

    def test_non_directory_returns_empty(self):
        assert local_git_recent_commits("/no/such/path", days=1) == []

    def test_empty_path_returns_empty(self):
        assert local_git_recent_commits("", days=1) == []

    def test_non_repo_directory_returns_empty(self, tmp_path):
        assert local_git_recent_commits(str(tmp_path), days=1) == []
