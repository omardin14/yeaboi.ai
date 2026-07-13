"""Unit tests for reporting/activity.gather_delivered_work (status filtering)."""

import pytest

from scrum_agent.reporting import activity


@pytest.fixture(autouse=True)
def _no_sprint_context(monkeypatch):
    # Isolate from any live tracker sprint read.
    import scrum_agent.standup.sprint_context as sc

    monkeypatch.setattr(sc, "gather", lambda *a, **k: sc.SprintContext(sprint_name="Sprint 9"))


def _fake_jira(items):
    def _f(project_key="", days=1):
        return items

    return _f


class TestIsCompleted:
    @pytest.mark.parametrize("status", ["Done", "done", "Closed", "Resolved", "Released", "Completed", "Shipped"])
    def test_completed_statuses(self, status):
        assert activity._is_completed(status)

    @pytest.mark.parametrize("status", ["In Progress", "To Do", "", "Blocked", "In Review"])
    def test_non_completed_statuses(self, status):
        assert not activity._is_completed(status)


class TestGatherDeliveredWork:
    def test_no_tracker_returns_warning(self, monkeypatch):
        monkeypatch.setattr("scrum_agent.config.get_jira_project_key", lambda: None)
        monkeypatch.setattr("scrum_agent.config.get_azure_devops_project", lambda: None)
        items, sprints, warnings = activity.gather_delivered_work("last_month")
        assert items == []
        assert warnings and "board" in warnings[0].lower()

    def test_filters_to_completed_only(self, monkeypatch):
        raw = [
            {"key": "P-1", "title": "done thing", "status": "Done", "author": "Ada", "timestamp": "2026-07-10"},
            {"key": "P-2", "title": "wip thing", "status": "In Progress", "author": "Bo", "timestamp": "2026-07-10"},
            {"key": "P-3", "title": "closed thing", "status": "Closed", "author": "Cy", "timestamp": "2026-07-10"},
        ]
        monkeypatch.setattr("scrum_agent.tools.jira.jira_recent_activity", _fake_jira(raw), raising=False)
        items, sprints, warnings = activity.gather_delivered_work("last_sprint", jira_project="PROJ")
        keys = {i.key for i in items}
        assert keys == {"P-1", "P-3"}
        assert all(i.source == "jira" for i in items)
        assert items[0].assignee in {"Ada", "Cy"}
        assert sprints == ["Sprint 9"]

    def test_days_override_skips_period_days_and_sprint_context(self, monkeypatch):
        captured = {}

        def _fake_jira_recent(project_key="", days=1):
            captured["days"] = days
            return [{"key": "P-1", "title": "t", "status": "Done", "author": "Ada", "timestamp": "2026-07-10"}]

        monkeypatch.setattr("scrum_agent.tools.jira.jira_recent_activity", _fake_jira_recent, raising=False)

        # period_days would return 14 for last_sprint; days_override must win.
        items, sprints_out, warnings = activity.gather_delivered_work(
            "last_sprint", jira_project="PROJ", days_override=90
        )
        assert captured["days"] == 90
        assert sprints_out == []  # sprint-context probe skipped
        assert len(items) == 1

    def test_activity_but_nothing_done_warns(self, monkeypatch):
        raw = [{"key": "P-9", "title": "wip", "status": "In Progress", "author": "Ada", "timestamp": "2026-07-10"}]
        monkeypatch.setattr("scrum_agent.tools.jira.jira_recent_activity", _fake_jira(raw), raising=False)
        items, sprints, warnings = activity.gather_delivered_work("last_sprint", jira_project="PROJ")
        assert items == []
        assert any("Done/Closed" in w for w in warnings)
