"""Unit tests for RetroStore persistence + serialization round-trips."""

from yeaboi.agent.state import RetroCard, RetroReport
from yeaboi.retro.store import RetroStore, _dict_to_retro_report, _retro_report_to_json


def _report(session_id="sess-1"):
    return RetroReport(
        date="2026-07-10",
        session_id=session_id,
        project_name="Demo",
        sprint_name="Sprint 5",
        cards=(
            RetroCard(
                id="a1",
                grid="went_well",
                text="ci",
                author="Sam",
                created_at="t",
                origin="web",
                reactions=(("👍", 3), ("🔥", 1)),
            ),
            RetroCard(id="a2", grid="action_items", text="fix", author="AI", created_at="t", origin="ai"),
        ),
        participants=("Sam",),
        generated_at="t2",
    )


class TestSerialization:
    def test_json_roundtrip(self):
        rep = _report()
        got = _dict_to_retro_report(__import__("json").loads(_retro_report_to_json(rep)))
        assert got == rep

    def test_missing_keys_deserialize_with_defaults(self):
        # An older/partial payload (no participants, card missing origin/reactions) still loads.
        d = {"session_id": "x", "cards": [{"grid": "demos", "text": "hi"}]}
        rep = _dict_to_retro_report(d)
        assert rep.session_id == "x"
        assert rep.cards[0].origin == "web" and rep.cards[0].author == ""
        assert rep.cards[0].reactions == ()
        assert rep.participants == ()

    def test_reactions_round_trip(self):
        rep = _report()
        got = _dict_to_retro_report(__import__("json").loads(_retro_report_to_json(rep)))
        assert dict(got.cards[0].reactions) == {"👍": 3, "🔥": 1}


class TestStore:
    def test_record_and_get_latest(self, tmp_path):
        db = tmp_path / "sessions.db"
        with RetroStore(db) as store:
            rid = store.record_run(_report())
            assert rid >= 1
            got = store.get_latest_report("sess-1")
        assert got is not None and len(got.cards) == 2 and got.cards[0].text == "ci"

    def test_get_latest_none_when_empty(self, tmp_path):
        with RetroStore(tmp_path / "sessions.db") as store:
            assert store.get_latest_report("nope") is None

    def test_latest_wins(self, tmp_path):
        db = tmp_path / "sessions.db"
        with RetroStore(db) as store:
            store.record_run(_report())
            newer = RetroReport(session_id="sess-1", date="2026-07-11", cards=(RetroCard(text="newer"),))
            store.record_run(newer)
            got = store.get_latest_report("sess-1")
        assert got.date == "2026-07-11"

    def test_history(self, tmp_path):
        db = tmp_path / "sessions.db"
        with RetroStore(db) as store:
            store.record_run(_report())
            hist = store.get_history("sess-1")
        assert hist and hist[0]["card_count"] == 2 and hist[0]["project_name"] == "Demo"
