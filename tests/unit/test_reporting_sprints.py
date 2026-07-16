"""Unit tests for reporting/sprints — quarter maths + sprint listing."""

from datetime import date

from yeaboi.reporting import sprints
from yeaboi.reporting.sprints import SprintRef


class TestQuarterBounds:
    def test_each_quarter(self):
        assert sprints.quarter_bounds(date(2026, 2, 15)) == ("Q1 2026", "2026-01-01", "2026-03-31")
        assert sprints.quarter_bounds(date(2026, 5, 1)) == ("Q2 2026", "2026-04-01", "2026-06-30")
        assert sprints.quarter_bounds(date(2026, 7, 13)) == ("Q3 2026", "2026-07-01", "2026-09-30")
        assert sprints.quarter_bounds(date(2026, 11, 30)) == ("Q4 2026", "2026-10-01", "2026-12-31")

    def test_year_boundaries(self):
        assert sprints.quarter_bounds(date(2026, 1, 1))[0] == "Q1 2026"
        assert sprints.quarter_bounds(date(2026, 12, 31)) == ("Q4 2026", "2026-10-01", "2026-12-31")


class TestMarkInQuarter:
    def test_overlap_cases(self):
        q_start, q_end = "2026-07-01", "2026-09-30"
        refs = [
            SprintRef("inside", "2026-07-06", "2026-07-19"),  # fully inside
            SprintRef("spanning-start", "2026-06-22", "2026-07-05"),  # crosses the boundary
            SprintRef("before", "2026-03-01", "2026-03-14"),  # fully outside
            SprintRef("undated", "", ""),  # no dates → not in quarter
        ]
        marked = {s.name: s.in_quarter for s in sprints.mark_in_quarter(refs, q_start, q_end)}
        assert marked == {"inside": True, "spanning-start": True, "before": False, "undated": False}


class TestListSprints:
    def test_prefers_jira(self, monkeypatch):
        monkeypatch.setattr(
            "yeaboi.tools.jira.jira_list_sprints",
            lambda project_key="", limit=30: [{"name": "S1", "start_date": "2026-07-01", "end_date": "2026-07-14"}],
            raising=False,
        )
        # AzDO would raise if called — assert it isn't.
        monkeypatch.setattr(
            "yeaboi.tools.azure_devops.azdevops_list_sprints",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("AzDO must not be called when Jira has sprints")),
            raising=False,
        )
        out = sprints.list_sprints({}, jira_project="PROJ", azdo_project="AZ")
        assert [s.name for s in out] == ["S1"]
        assert out[0].source == "jira"

    def test_falls_back_to_azdo(self, monkeypatch):
        monkeypatch.setattr("yeaboi.tools.jira.jira_list_sprints", lambda *a, **k: [], raising=False)
        monkeypatch.setattr(
            "yeaboi.tools.azure_devops.azdevops_list_sprints",
            lambda project="", limit=30: [{"name": "IT-1", "start_date": "2026-07-01", "end_date": "2026-07-14"}],
            raising=False,
        )
        out = sprints.list_sprints({}, jira_project="PROJ", azdo_project="AZ")
        assert out[0].source == "azuredevops"

    def test_falls_back_to_plan(self, monkeypatch):
        monkeypatch.setattr("yeaboi.tools.jira.jira_list_sprints", lambda *a, **k: [], raising=False)
        monkeypatch.setattr("yeaboi.tools.azure_devops.azdevops_list_sprints", lambda *a, **k: [], raising=False)
        state = {
            "sprints": [{"name": "Sprint 1"}, {"name": "Sprint 2"}],
            "sprint_start_date": "2026-06-01",
            "sprint_length_weeks": 2,
        }
        out = sprints.list_sprints(state, jira_project="PROJ", azdo_project="AZ")
        assert [s.name for s in out] == ["Sprint 1", "Sprint 2"]
        assert out[0].source == "plan"
        assert out[0].start_date == "2026-06-01" and out[0].end_date == "2026-06-14"
        assert out[1].start_date == "2026-06-15"

    def test_empty_when_nothing_available(self, monkeypatch):
        monkeypatch.setattr("yeaboi.tools.jira.jira_list_sprints", lambda *a, **k: [], raising=False)
        monkeypatch.setattr("yeaboi.tools.azure_devops.azdevops_list_sprints", lambda *a, **k: [], raising=False)
        assert sprints.list_sprints({}, jira_project="PROJ", azdo_project="AZ") == []

    def test_limit_keeps_most_recent(self, monkeypatch):
        rows = [
            {"name": f"S{i}", "start_date": f"2026-01-{i:02d}", "end_date": f"2026-01-{i:02d}"} for i in range(1, 20)
        ]
        monkeypatch.setattr("yeaboi.tools.jira.jira_list_sprints", lambda *a, **k: rows, raising=False)
        out = sprints.list_sprints({}, jira_project="PROJ", limit=5)
        assert len(out) == 5
        assert [s.name for s in out] == ["S15", "S16", "S17", "S18", "S19"]  # newest last
