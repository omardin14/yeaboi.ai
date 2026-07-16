"""Unit tests for PerformanceStore — round-trips, action-item loop, notes."""

import pytest

from yeaboi.agent.state import OneOnOnePrep, OneOnOneRecord, SixMonthReview
from yeaboi.performance.store import PerformanceStore


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "sessions.db"


class TestPrepRoundTrip:
    def test_record_and_get_latest_prep(self, db_path):
        prep = OneOnOnePrep(
            engineer="Ada",
            date="2026-07-12",
            talking_points=("a", "b"),
            goals=("ship auth",),
            carried_action_items=("write tests",),
        )
        with PerformanceStore(db_path) as store:
            store.record_prep(prep, session_id="s1")
            got = store.get_latest_prep("Ada")
        assert got is not None
        assert got.talking_points == ("a", "b")
        assert got.goals == ("ship auth",)
        assert got.carried_action_items == ("write tests",)

    def test_get_latest_prep_none_when_absent(self, db_path):
        with PerformanceStore(db_path) as store:
            assert store.get_latest_prep("Nobody") is None


class TestCompletionLoop:
    def test_open_action_items_from_latest_completion(self, db_path):
        with PerformanceStore(db_path) as store:
            store.record_completion(OneOnOneRecord(engineer="Ada", date="2026-07-01", action_items=("old",)))
            store.record_completion(OneOnOneRecord(engineer="Ada", date="2026-07-12", action_items=("new1", "new2")))
            # Newest completion's actions win (this is what the next prep carries).
            assert store.get_open_action_items("Ada") == ("new1", "new2")

    def test_open_action_items_empty_when_no_completion(self, db_path):
        with PerformanceStore(db_path) as store:
            assert store.get_open_action_items("Ada") == ()

    def test_recent_completions_newest_first(self, db_path):
        with PerformanceStore(db_path) as store:
            store.record_completion(OneOnOneRecord(engineer="Ada", date="2026-07-01", highlights=("h1",)))
            store.record_completion(OneOnOneRecord(engineer="Ada", date="2026-07-12", highlights=("h2",)))
            recents = store.get_recent_completions("Ada")
        assert [r.date for r in recents] == ["2026-07-12", "2026-07-01"]


class TestReviewRoundTrip:
    def test_record_and_get_latest_review(self, db_path):
        review = SixMonthReview(
            engineer="Ada",
            period_start="2026-01-12",
            period_end="2026-07-12",
            strengths=("ownership",),
            overall="Strong half.",
            framework_used="default",
        )
        with PerformanceStore(db_path) as store:
            store.record_review(review)
            got = store.get_latest_review("Ada")
        assert got is not None
        assert got.strengths == ("ownership",)
        assert got.overall == "Strong half."


class TestNotes:
    def test_add_and_get_notes_newest_first(self, db_path):
        with PerformanceStore(db_path) as store:
            store.add_note("Ada", "first")
            store.add_note("Ada", "second")
            notes = store.get_notes("Ada")
        assert [n["note_text"] for n in notes] == ["second", "first"]


class TestTeamWide:
    def test_all_open_action_items_latest_per_engineer(self, db_path):
        with PerformanceStore(db_path) as store:
            store.record_completion(OneOnOneRecord(engineer="Ada", date="2026-07-01", action_items=("a-old",)))
            store.record_completion(OneOnOneRecord(engineer="Ada", date="2026-07-12", action_items=("a-new",)))
            store.record_completion(OneOnOneRecord(engineer="Bob", date="2026-07-10", action_items=("b1",)))
            allitems = store.get_all_open_action_items()
        assert allitems["Ada"] == ("a-new",)
        assert allitems["Bob"] == ("b1",)

    def test_recent_reviews(self, db_path):
        with PerformanceStore(db_path) as store:
            store.record_review(SixMonthReview(engineer="Ada", overall="x"))
            store.record_review(SixMonthReview(engineer="Bob", overall="y"))
            reviews = store.get_recent_reviews()
        assert {r.engineer for r in reviews} == {"Ada", "Bob"}
