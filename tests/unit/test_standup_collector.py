"""Unit tests for the standup recent-activity collector."""

from yeaboi.standup import collector
from yeaboi.standup.collector import (
    SOURCE_GITHUB,
    SOURCE_JIRA,
    SOURCE_LOCAL_GIT,
    SOURCE_NOTION,
    ActivityBundle,
    collect_recent_activity,
)


class TestActivityBundle:
    def test_authors_dedup_preserves_order(self):
        b = ActivityBundle(
            items=[
                {"author": "Alice"},
                {"author": "Bob"},
                {"author": "Alice"},
                {"author": ""},
                {"author": "  "},
            ]
        )
        assert b.authors() == ["Alice", "Bob"]

    def test_total(self):
        b = ActivityBundle(items=[{"author": "x"}, {"author": "y"}])
        assert b.total() == 2


class TestResolveSources:
    def test_explicit_wins(self):
        got = collector._resolve_sources(
            {SOURCE_JIRA},
            jira_project="",
            azdo_project="",
            github_repo="owner/repo",
            local_repo_path="",
            confluence_space="",
        )
        assert got == {SOURCE_JIRA}

    def test_auto_enables_from_params(self):
        got = collector._resolve_sources(
            None,
            jira_project="PROJ",
            azdo_project="",
            github_repo="owner/repo",
            local_repo_path="/tmp/r",
            confluence_space="",
        )
        assert got == {SOURCE_JIRA, SOURCE_GITHUB, SOURCE_LOCAL_GIT}

    def test_auto_enables_notion_from_root(self):
        got = collector._resolve_sources(
            None,
            jira_project="",
            azdo_project="",
            github_repo="",
            local_repo_path="",
            confluence_space="",
            notion_root="root123",
        )
        assert got == {SOURCE_NOTION}


class TestCollect:
    def test_tags_source_and_counts(self, monkeypatch):
        monkeypatch.setattr(
            "yeaboi.tools.jira.jira_recent_activity",
            lambda project, days=1: [{"author": "Alice", "kind": "issue", "title": "t"}],
        )
        monkeypatch.setattr(
            "yeaboi.tools.local_git.local_git_recent_commits",
            lambda path, days=1: [{"author": "Bob", "kind": "commit", "title": "c"}],
        )
        bundle = collect_recent_activity(
            days=1,
            sources={SOURCE_JIRA, SOURCE_LOCAL_GIT},
            jira_project="PROJ",
            local_repo_path="/tmp/r",
        )
        assert bundle.total() == 2
        assert {i["source"] for i in bundle.items} == {SOURCE_JIRA, SOURCE_LOCAL_GIT}
        assert dict(bundle.counts) == {SOURCE_JIRA: 1, SOURCE_LOCAL_GIT: 1}

    def test_failing_source_does_not_abort(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr("yeaboi.tools.jira.jira_recent_activity", boom)
        monkeypatch.setattr(
            "yeaboi.tools.local_git.local_git_recent_commits",
            lambda path, days=1: [{"author": "Bob", "kind": "commit", "title": "c"}],
        )
        bundle = collect_recent_activity(
            sources={SOURCE_JIRA, SOURCE_LOCAL_GIT},
            jira_project="PROJ",
            local_repo_path="/tmp/r",
        )
        # jira failed → no count recorded; local git still collected.
        assert bundle.total() == 1
        assert dict(bundle.counts) == {SOURCE_LOCAL_GIT: 1}

    def test_github_merges_commits_and_prs(self, monkeypatch):
        monkeypatch.setattr(
            "yeaboi.tools.github.github_recent_commits",
            lambda repo, days=1: [{"author": "A", "kind": "commit", "title": "c"}],
        )
        monkeypatch.setattr(
            "yeaboi.tools.github.github_recent_prs",
            lambda repo, days=1: [{"author": "A", "kind": "pr", "title": "p"}],
        )
        bundle = collect_recent_activity(sources={SOURCE_GITHUB}, github_repo="owner/repo")
        assert dict(bundle.counts) == {SOURCE_GITHUB: 2}
        assert {i["kind"] for i in bundle.items} == {"commit", "pr"}

    def test_notion_source_collected(self, monkeypatch):
        monkeypatch.setattr(
            "yeaboi.tools.notion.notion_recent_pages",
            lambda root_id, days=1: [{"author": "Alice", "kind": "page", "title": "Doc", "timestamp": "", "key": "1"}],
        )
        bundle = collect_recent_activity(sources={SOURCE_NOTION}, notion_root="root123")
        assert dict(bundle.counts) == {SOURCE_NOTION: 1}
        assert bundle.items[0]["source"] == SOURCE_NOTION

    def test_no_sources_enabled_is_empty(self):
        bundle = collect_recent_activity(sources=set())
        assert bundle.total() == 0
        assert bundle.counts == []

    def test_source_auth_error_recorded(self, monkeypatch):
        from yeaboi.standup.errors import StandupSourceError

        def auth_fail(project, days=1):
            raise StandupSourceError("jira", "authentication failed — check token")

        monkeypatch.setattr("yeaboi.tools.jira.jira_recent_activity", auth_fail)
        monkeypatch.setattr(
            "yeaboi.tools.local_git.local_git_recent_commits",
            lambda path, days=1: [{"author": "Bob", "kind": "commit", "title": "c"}],
        )
        bundle = collect_recent_activity(
            sources={SOURCE_JIRA, SOURCE_LOCAL_GIT}, jira_project="PROJ", local_repo_path="/tmp/r"
        )
        # Jira auth error surfaced; local git still collected.
        assert bundle.errors == [("jira", "authentication failed — check token")]
        assert dict(bundle.counts) == {SOURCE_LOCAL_GIT: 1}
        assert bundle.total() == 1
