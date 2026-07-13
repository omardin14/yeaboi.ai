"""Unit tests for per-engineer activity gathering (mocked sources + sprint ctx)."""

from scrum_agent.performance import activity
from scrum_agent.standup.sprint_context import SprintContext


def _patch_sprint(monkeypatch, *, name="Sprint 5", start="2026-07-06"):
    monkeypatch.setattr(
        "scrum_agent.standup.sprint_context.gather",
        lambda state, **kw: SprintContext(sprint_name=name, start_date=start, sprint_length_weeks=2),
    )


class TestGatherEngineerActivity:
    def test_filters_by_engineer_and_splits_by_sprint(self, monkeypatch):
        _patch_sprint(monkeypatch)
        monkeypatch.setattr(
            "scrum_agent.tools.jira.jira_recent_activity",
            lambda project_key, days=1: [
                {
                    "author": "Ada",
                    "key": "P-1",
                    "title": "auth",
                    "status": "Done",
                    "kind": "issue",
                    "timestamp": "2026-07-10T00:00:00",
                },
                {
                    "author": "Ada",
                    "key": "P-2",
                    "title": "old work",
                    "status": "Done",
                    "kind": "issue",
                    "timestamp": "2026-06-20T00:00:00",
                },
                {
                    "author": "Bob",
                    "key": "P-3",
                    "title": "not ada",
                    "status": "Done",
                    "kind": "issue",
                    "timestamp": "2026-07-10T00:00:00",
                },
            ],
        )
        act = activity.gather_engineer_activity("Ada", jira_project="PROJ")
        assert act.total_items == 2
        buckets = {s.key: s.sprint for s in act.stories}
        assert buckets["P-1"] == "current"  # on/after start date
        assert buckets["P-2"] == "previous"  # before start date
        assert "P-3" not in buckets  # Bob's work filtered out
        assert act.current_sprint == "Sprint 5"

    def test_empty_when_no_tracker(self, monkeypatch):
        monkeypatch.setattr("scrum_agent.config.get_jira_project_key", lambda: "")
        monkeypatch.setattr("scrum_agent.config.get_azure_devops_project", lambda: "")
        act = activity.gather_engineer_activity("Ada")
        assert act.total_items == 0
        assert act.stories == ()

    def test_case_insensitive_author_match(self, monkeypatch):
        _patch_sprint(monkeypatch)
        monkeypatch.setattr(
            "scrum_agent.tools.jira.jira_recent_activity",
            lambda project_key, days=1: [
                {
                    "author": "ada lovelace",
                    "key": "P-1",
                    "title": "x",
                    "status": "Done",
                    "kind": "issue",
                    "timestamp": "2026-07-10T00:00:00",
                },
            ],
        )
        act = activity.gather_engineer_activity("Ada Lovelace", jira_project="PROJ")
        assert act.total_items == 1
