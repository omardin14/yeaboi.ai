"""Tests for src/yeaboi/context/window.py — dates from a window, and where the sprint grid comes from."""

from __future__ import annotations

from datetime import date

import pytest

from yeaboi.context import window as win
from yeaboi.context.scope import Window
from yeaboi.context.window import SprintCalendar, load_sprint_calendar, resolve_window, window_label
from yeaboi.reporting.sprints import SprintRef

TODAY = date(2026, 9, 11)  # a Friday
GRID = SprintCalendar(anchor=date(2026, 8, 31), length_weeks=2, source="settings", numbered_from=12)


@pytest.fixture(autouse=True)
def _fresh_memo():
    win.clear_calendar_memo()
    yield
    win.clear_calendar_memo()


class TestSprintCalendar:
    def test_bounds_on_the_grid(self):
        assert GRID.sprint_bounds(TODAY) == (date(2026, 8, 31), date(2026, 9, 13))
        assert GRID.sprint_bounds(date(2026, 8, 30)) == (date(2026, 8, 17), date(2026, 8, 30))

    def test_numbers_count_from_the_anchor(self):
        assert GRID.sprint_number(TODAY) == 12
        assert GRID.sprint_number(date(2026, 8, 20)) == 11
        assert GRID.sprint_number(date(2025, 1, 1)) is None

    def test_known_sprints_win_over_the_grid(self):
        cal = SprintCalendar(
            anchor=date(2026, 9, 2),
            length_weeks=2,
            source="tracker",
            known=(SprintRef(name="Sprint 40", start_date="2026-09-02", end_date="2026-09-15", source="jira"),),
        )
        assert cal.sprint_bounds(TODAY) == (date(2026, 9, 2), date(2026, 9, 15))
        assert cal.sprint_number(TODAY) == 40
        assert cal.sprint_number(date(2026, 1, 1)) is None  # tracker grid: no number without a sprint


class TestResolveWindow:
    def test_all_is_unbounded(self):
        assert resolve_window(Window(), today=TODAY) == ("", "")

    def test_two_sprints(self):
        assert resolve_window(Window(kind="sprints", count=2), today=TODAY, calendar=GRID) == (
            "2026-08-17",
            "2026-09-11",
        )

    def test_one_sprint_starts_at_the_current_sprint(self):
        assert resolve_window(Window(kind="sprints", count=1), today=TODAY, calendar=GRID)[0] == "2026-08-31"

    def test_sprints_without_a_calendar_fall_back_to_two_weeks(self):
        start, end = resolve_window(Window(kind="sprints", count=1), today=TODAY)
        assert (start, end) == ("2026-09-11", "2026-09-11")

    @pytest.mark.parametrize(
        ("kind", "start"), [("month", "2026-08-12"), ("quarter", "2026-06-12"), ("year", "2025-09-11")]
    )
    def test_rolling_windows(self, kind, start):
        assert resolve_window(Window(kind=kind), today=TODAY) == (start, "2026-09-11")

    def test_custom_normalises_and_defaults_the_end(self):
        assert resolve_window(Window(kind="custom", start="2026-08-31", end="2026-08-01"), today=TODAY) == (
            "2026-08-01",
            "2026-08-31",
        )
        assert resolve_window(Window(kind="custom", start="2026-08-01"), today=TODAY) == ("2026-08-01", "2026-09-11")
        assert resolve_window(Window(kind="custom"), today=TODAY) == ("", "")


class TestWindowLabel:
    def test_labels(self):
        assert window_label("", "") == "all time"
        assert window_label("2026-08-04", "2026-09-11") == "4 Aug – 11 Sep"
        assert window_label("2025-12-20", "2026-01-05") == "20 Dec 2025 – 5 Jan 2026"
        assert window_label("", "2026-09-11") == "until 11 Sep"
        assert window_label("2026-09-01", "") == "from 1 Sep"


class TestLoadSprintCalendar:
    @pytest.fixture(autouse=True)
    def _no_sources(self, monkeypatch):
        monkeypatch.setattr(win, "_from_tracker", lambda: None)
        monkeypatch.setattr(win, "_from_plan", lambda _db: None)
        monkeypatch.delenv("YEABOI_SPRINT_ANCHOR_DATE", raising=False)
        monkeypatch.delenv("YEABOI_SPRINT_LENGTH_WEEKS", raising=False)

    def test_default_is_monday_of_this_week(self):
        cal = load_sprint_calendar(today=TODAY, use_tracker=False)
        assert cal.source == "default" and cal.anchor == date(2026, 9, 7) and cal.length_weeks == 2

    def test_settings_come_before_the_default(self, monkeypatch):
        monkeypatch.setenv("YEABOI_SPRINT_ANCHOR_DATE", "2026-08-31")
        monkeypatch.setenv("YEABOI_SPRINT_LENGTH_WEEKS", "3")
        cal = load_sprint_calendar(today=TODAY, use_tracker=False)
        assert (cal.source, cal.anchor, cal.length_weeks) == ("settings", date(2026, 8, 31), 3)

    def test_plan_comes_before_settings(self, monkeypatch):
        monkeypatch.setenv("YEABOI_SPRINT_ANCHOR_DATE", "2026-08-31")
        plan = SprintCalendar(anchor=date(2026, 7, 6), length_weeks=1, source="plan", numbered_from=7)
        monkeypatch.setattr(win, "_from_plan", lambda _db: plan)
        assert load_sprint_calendar(today=TODAY, use_tracker=False) is plan

    def test_tracker_comes_first_and_only_when_asked(self, monkeypatch):
        tracker = SprintCalendar(anchor=date(2026, 9, 2), length_weeks=2, source="tracker")
        monkeypatch.setattr(win, "_from_tracker", lambda: tracker)
        assert load_sprint_calendar(today=TODAY).source == "tracker"
        assert load_sprint_calendar(today=TODAY, use_tracker=False).source == "default"

    def test_memo_holds_for_a_minute(self, monkeypatch):
        calls = []
        monkeypatch.setattr(win, "_from_tracker", lambda: calls.append(1) or None)
        load_sprint_calendar(today=TODAY)
        load_sprint_calendar(today=TODAY)
        assert len(calls) == 1
        win.clear_calendar_memo()
        load_sprint_calendar(today=TODAY)
        assert len(calls) == 2


class TestFromPlanAndTracker:
    def test_from_plan_reads_the_grid_and_dates_every_sprint(self, monkeypatch):
        import yeaboi.ship.plans as plans

        state = {
            "sprint_start_date": "2026-07-06",
            "sprint_length_weeks": 2,
            "starting_sprint_number": 0,
            "sprints": [{"name": "A"}],
        }
        monkeypatch.setattr(plans, "latest_plan_with_work", lambda _db=None, **_kw: (state, "p1", "Plan"))
        cal = win._from_plan(None)
        assert cal.source == "plan" and cal.numbered_from == 1
        assert cal.known[0].start_date == "2026-07-06" and cal.known[0].end_date == "2026-07-19"

    def test_from_plan_without_a_start_date_is_none(self, monkeypatch):
        import yeaboi.ship.plans as plans

        monkeypatch.setattr(plans, "latest_plan_with_work", lambda _db=None, **_kw: ({"sprints": []}, "p1", ""))
        assert win._from_plan(None) is None
        monkeypatch.setattr(plans, "latest_plan_with_work", lambda _db=None, **_kw: None)
        assert win._from_plan(None) is None

    def test_from_tracker_infers_the_length_from_the_newest_sprint(self, monkeypatch):
        import yeaboi.reporting.sprints as sprints

        monkeypatch.setattr("yeaboi.config.get_jira_project_key", lambda: "PROJ")
        monkeypatch.setattr("yeaboi.config.get_azure_devops_project", lambda: "")
        refs = [SprintRef(name="Sprint 3", start_date="2026-08-19", end_date="2026-09-08", source="jira")]
        monkeypatch.setattr(sprints, "list_sprints", lambda *_a, **_k: refs)
        cal = win._from_tracker()
        assert cal.source == "tracker" and cal.length_weeks == 3 and cal.anchor == date(2026, 8, 19)

    def test_from_tracker_is_none_without_a_project_or_on_failure(self, monkeypatch):
        monkeypatch.setattr("yeaboi.config.get_jira_project_key", lambda: "")
        monkeypatch.setattr("yeaboi.config.get_azure_devops_project", lambda: "")
        assert win._from_tracker() is None
        monkeypatch.setattr("yeaboi.config.get_jira_project_key", lambda: "PROJ")

        def boom(*_a, **_k):
            raise RuntimeError("down")

        monkeypatch.setattr("yeaboi.reporting.sprints.list_sprints", boom)
        assert win._from_tracker() is None
