"""Unit tests for the retro action-items engine (mocked LLM)."""

import json

from scrum_agent.retro import engine
from scrum_agent.retro.board import RetroBoard


class _FakeResp:
    def __init__(self, content):
        self.content = content
        self.response_metadata = {}


def _fake_llm(content):
    return lambda **k: type("L", (), {"invoke": lambda self, m: _FakeResp(content)})()


class TestParse:
    def test_plain_json(self):
        assert engine._parse_action_items('{"action_items": ["a", "b"]}') == ["a", "b"]

    def test_markdown_fenced(self):
        raw = '```json\n{"action_items": ["x"]}\n```'
        assert engine._parse_action_items(raw) == ["x"]

    def test_bare_list(self):
        assert engine._parse_action_items('["only", "list"]') == ["only", "list"]

    def test_garbage_returns_empty(self):
        assert engine._parse_action_items("not json at all") == []

    def test_strips_blank_items(self):
        assert engine._parse_action_items('{"action_items": ["a", "  ", ""]}') == ["a"]


class TestFallback:
    def test_builds_address_items(self):
        items = engine._build_fallback_action_items(["flaky tests", "slow CI", ""])
        assert items == ["Address: flaky tests", "Address: slow CI"]


class TestGenerateActionItems:
    def _seed(self):
        b = RetroBoard("s", "Proj")
        b.add_card(grid="didnt_go_well", text="flaky tests", author="Rae")
        b.add_card(grid="went_well", text="fast deploys", author="Sam")
        return b

    def test_empty_board_returns_hint(self):
        b = RetroBoard("s")
        msg = engine.generate_action_items(b)
        assert "Add some cards" in msg
        assert b.total() == 0

    def test_happy_path_with_llm(self, monkeypatch):
        b = self._seed()
        monkeypatch.setattr("scrum_agent.config.is_llm_configured", lambda: (True, ""))
        monkeypatch.setattr("scrum_agent.agent.llm.track_usage", lambda resp: None)
        payload = json.dumps({"action_items": ["Add a CI retry guard", "Split the flaky suite"]})
        monkeypatch.setattr("scrum_agent.agent.llm.get_llm", _fake_llm(payload))
        msg = engine.generate_action_items(b)
        assert "Generated 2" in msg
        assert len(b.cards_by_grid()["action_items"]) == 2

    def test_not_configured_uses_fallback(self, monkeypatch):
        b = self._seed()
        monkeypatch.setattr("scrum_agent.config.is_llm_configured", lambda: (False, "ANTHROPIC_API_KEY not set"))

        def _should_not_call(**k):
            raise AssertionError("get_llm must not be called when unconfigured")

        monkeypatch.setattr("scrum_agent.agent.llm.get_llm", _should_not_call)
        msg = engine.generate_action_items(b)
        assert "unavailable" in msg.lower()
        # Deterministic fallback added the one problem card as an action item.
        assert len(b.cards_by_grid()["action_items"]) == 1

    def test_reaction_counts_annotate_prompt(self, monkeypatch):
        b = self._seed()
        # React to the "flaky tests" problem card.
        problem = b.cards_by_grid()["didnt_go_well"][0]
        b.toggle_reaction(problem.id, "👍", "p1")
        b.toggle_reaction(problem.id, "🔥", "p2")
        monkeypatch.setattr("scrum_agent.config.is_llm_configured", lambda: (True, ""))
        monkeypatch.setattr("scrum_agent.agent.llm.track_usage", lambda resp: None)

        captured = {}

        def _fake(**k):
            def _invoke(self, messages):
                captured["prompt"] = messages[0].content
                return _FakeResp('{"action_items": ["x"]}')

            return type("L", (), {"invoke": _invoke})()

        monkeypatch.setattr("scrum_agent.agent.llm.get_llm", _fake)
        engine.generate_action_items(b)
        assert "[2 reactions]" in captured["prompt"]

    def test_llm_error_falls_back(self, monkeypatch):
        b = self._seed()
        monkeypatch.setattr("scrum_agent.config.is_llm_configured", lambda: (True, ""))
        monkeypatch.setattr("scrum_agent.agent.llm.track_usage", lambda resp: None)

        def boom(self, m):
            raise RuntimeError("network down")

        monkeypatch.setattr("scrum_agent.agent.llm.get_llm", lambda **k: type("L", (), {"invoke": boom})())
        msg = engine.generate_action_items(b)
        assert "failed" in msg.lower()
        assert len(b.cards_by_grid()["action_items"]) == 1
