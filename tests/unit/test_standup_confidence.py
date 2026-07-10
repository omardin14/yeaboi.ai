"""Unit tests for deterministic sprint-day + confidence scoring."""

from datetime import date

from scrum_agent.standup import confidence
from scrum_agent.standup.confidence import (
    LABEL_AT_RISK,
    LABEL_BEHIND,
    LABEL_INSUFFICIENT,
    LABEL_ON_TRACK,
    working_days_between,
)


class TestWorkingDaysBetween:
    def test_full_week(self):
        # Mon 2026-07-06 .. Fri 2026-07-10 = 5 working days
        assert working_days_between(date(2026, 7, 6), date(2026, 7, 10)) == 5

    def test_excludes_weekend(self):
        # Mon .. Sun spans a weekend → still 5
        assert working_days_between(date(2026, 7, 6), date(2026, 7, 12)) == 5

    def test_excludes_holidays(self):
        holidays = {date(2026, 7, 8)}  # Wednesday off
        assert working_days_between(date(2026, 7, 6), date(2026, 7, 10), holidays) == 4

    def test_end_before_start(self):
        assert working_days_between(date(2026, 7, 10), date(2026, 7, 6)) == 0


class TestCompute:
    def test_no_start_date_is_insufficient(self):
        r = confidence.compute(start_date="", capacity_points=20)
        assert r.confidence_label == LABEL_INSUFFICIENT
        assert r.sprint_day == 0

    def test_no_capacity_reports_day_but_not_confidence(self):
        # Sprint started Mon; today is Wed of the same week → day 3 of 10.
        r = confidence.compute(
            start_date="2026-07-06",
            sprint_length_weeks=2,
            capacity_points=0,
            today=date(2026, 7, 8),
        )
        assert r.sprint_day == 3
        assert r.sprint_total_days == 10
        assert r.confidence_label == LABEL_INSUFFICIENT

    def test_on_track(self):
        # Day 5 of 10, capacity 20 → ideal = 10; completed 10 → 100% On track.
        r = confidence.compute(
            start_date="2026-07-06",
            sprint_length_weeks=2,
            capacity_points=20,
            completed_points=10,
            activity_count=5,
            today=date(2026, 7, 10),
        )
        assert r.sprint_day == 5
        assert r.confidence_pct == 100
        assert r.confidence_label == LABEL_ON_TRACK

    def test_at_risk(self):
        # Day 5 of 10, ideal 10, completed 8 → 80% At risk.
        r = confidence.compute(
            start_date="2026-07-06",
            sprint_length_weeks=2,
            capacity_points=20,
            completed_points=8,
            activity_count=3,
            today=date(2026, 7, 10),
        )
        assert r.confidence_pct == 80
        assert r.confidence_label == LABEL_AT_RISK

    def test_behind(self):
        # Day 5 of 10, ideal 10, completed 4 → 40% Behind.
        r = confidence.compute(
            start_date="2026-07-06",
            sprint_length_weeks=2,
            capacity_points=20,
            completed_points=4,
            activity_count=2,
            today=date(2026, 7, 10),
        )
        assert r.confidence_pct == 40
        assert r.confidence_label == LABEL_BEHIND

    def test_ahead_is_capped_at_100(self):
        r = confidence.compute(
            start_date="2026-07-06",
            sprint_length_weeks=2,
            capacity_points=20,
            completed_points=18,
            activity_count=5,
            today=date(2026, 7, 8),
        )
        assert r.confidence_pct == 100
        assert r.confidence_label == LABEL_ON_TRACK

    def test_silence_penalty_past_day_one(self):
        # Day 5, would be 100% on track, but zero activity → *0.7 = 70.
        r = confidence.compute(
            start_date="2026-07-06",
            sprint_length_weeks=2,
            capacity_points=20,
            completed_points=10,
            activity_count=0,
            today=date(2026, 7, 10),
        )
        assert r.confidence_pct == 70
        assert "No recent activity" in r.confidence_rationale

    def test_holidays_reduce_total_days(self):
        holidays = {date(2026, 7, 8)}
        r = confidence.compute(
            start_date="2026-07-06",
            sprint_length_weeks=2,
            capacity_points=20,
            completed_points=5,
            activity_count=1,
            today=date(2026, 7, 7),
            holidays=holidays,
        )
        # 2 sprint weeks = 10 weekdays, minus 1 holiday in range = 9 total.
        assert r.sprint_total_days == 9
