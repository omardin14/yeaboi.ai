"""Tests for agent/chat_intake.py — greeting and size resolution."""

from unittest.mock import MagicMock, patch

import pytest

from yeaboi.agent.chat_intake import (
    GREETING_TEXT,
    SIZE_QUESTION_TEXT,
    classify_size_from_description,
    parse_size_reply,
    resolve_intake_mode,
)

_INVOKE_JSON = "yeaboi.agent.llm.invoke_json"


def _json_response(content: str) -> MagicMock:
    response = MagicMock()
    response.content = content
    return response


class TestParseSizeReply:
    def test_small_replies(self):
        for reply in ("1", "small", "Small", " SMALL ", "tiny", "a ticket", "quick", "small one", "small."):
            assert parse_size_reply(reply) == "small_project", reply

    def test_large_replies(self):
        for reply in ("2", "large", "big", "epic", "huge", "Large!", "big one"):
            assert parse_size_reply(reply) == "smart", reply

    def test_non_size_text_is_none(self):
        # Sentences containing size words must NOT parse — they're descriptions.
        for reply in ("", "a small app for a huge market", "3", "yes", "build me a todo app"):
            assert parse_size_reply(reply) is None, reply


class TestClassifySize:
    def test_small_maps_to_small_project(self):
        with patch(_INVOKE_JSON, return_value=_json_response('{"size": "small"}')):
            assert classify_size_from_description("fix the login button") == "small_project"

    def test_large_maps_to_smart(self):
        with patch(_INVOKE_JSON, return_value=_json_response('{"size": "large"}')):
            assert classify_size_from_description("build a marketplace") == "smart"

    def test_unclear_is_none(self):
        with patch(_INVOKE_JSON, return_value=_json_response('{"size": "unclear"}')):
            assert classify_size_from_description("something") is None

    def test_fenced_json_is_stripped(self):
        with patch(_INVOKE_JSON, return_value=_json_response('```json\n{"size": "small"}\n```')):
            assert classify_size_from_description("small fix") == "small_project"

    def test_bad_json_falls_back_to_none(self):
        with patch(_INVOKE_JSON, return_value=_json_response("not json at all")):
            assert classify_size_from_description("something") is None

    def test_provider_error_falls_back_to_none(self):
        with patch(_INVOKE_JSON, side_effect=ValueError("boom")):
            assert classify_size_from_description("something") is None

    def test_auth_error_reraises(self):
        # Broken credentials must surface, not hide behind an extra question.
        with (
            patch(_INVOKE_JSON, side_effect=RuntimeError("401 unauthorized")),
            patch("yeaboi.agent.nodes._should_reraise_llm_error", return_value=True),
            pytest.raises(RuntimeError, match="401"),
        ):
            classify_size_from_description("something")


class TestResolveIntakeMode:
    def test_bare_size_answer_has_no_description(self):
        assert resolve_intake_mode("small") == ("small_project", "")
        assert resolve_intake_mode("2") == ("smart", "")

    def test_short_text_kept_as_description_mode_unknown(self):
        # Short but real descriptions: keep the text, ask the size question.
        mode, description = resolve_intake_mode("todo app in react")
        assert mode is None
        assert description == "todo app in react"

    def test_long_description_is_classified(self):
        text = "we are building a full customer portal with billing, auth and admin dashboards"
        with patch("yeaboi.agent.chat_intake.classify_size_from_description", return_value="smart") as classify:
            assert resolve_intake_mode(text) == ("smart", text)
        classify.assert_called_once_with(text)

    def test_unclear_classification_keeps_description(self):
        text = "one two three four five six seven eight nine"
        with patch("yeaboi.agent.chat_intake.classify_size_from_description", return_value=None):
            assert resolve_intake_mode(text) == (None, text)


class TestScriptedTexts:
    def test_greeting_mentions_help_and_size_commands(self):
        assert "/help" in GREETING_TEXT
        assert "/small" in GREETING_TEXT
        assert "/large" in GREETING_TEXT

    def test_size_question_uses_numbered_choice_format(self):
        # Same [1]/[2] shape as intake choice questions — one visual language.
        assert "[1]" in SIZE_QUESTION_TEXT
        assert "[2]" in SIZE_QUESTION_TEXT
        assert "Small" in SIZE_QUESTION_TEXT
        assert "Large" in SIZE_QUESTION_TEXT


class TestSeedAnalysisProfile:
    def test_an_empty_id_seeds_nothing(self):
        from yeaboi.agent.chat_intake import seed_analysis_profile

        state: dict = {}
        seed_analysis_profile(state, "")
        assert state == {}

    def test_the_profile_and_its_practised_dod_are_seeded(self):
        from yeaboi.agent.chat_intake import seed_analysis_profile

        examples = {
            "proposed_dod": {
                "items": [
                    {"practice": "Tests pass", "status": "established"},
                    {"practice": "Docs updated", "status": "emerging"},
                    {"practice": "Perf budget", "status": "aspirational"},
                ]
            }
        }
        with patch("yeaboi.agent.nodes._load_profile_by_id", return_value=(object(), examples)):
            state: dict = {}
            seed_analysis_profile(state, "jira-PROJ")
        assert state["analysis_profile_id"] == "jira-PROJ"
        assert state["custom_dod_items"] == ("Tests pass", "Docs updated")

    def test_an_unreadable_profile_keeps_the_id_and_the_default_dod(self):
        from yeaboi.agent.chat_intake import seed_analysis_profile

        with patch("yeaboi.agent.nodes._load_profile_by_id", side_effect=RuntimeError("db gone")):
            state: dict = {}
            seed_analysis_profile(state, "jira-PROJ")
        assert state == {"analysis_profile_id": "jira-PROJ"}

    def test_nothing_is_seeded_when_the_analysis_source_is_off(self):
        import json

        from yeaboi.agent.chat_intake import seed_analysis_profile

        with patch("yeaboi.agent.nodes._load_profile_by_id", side_effect=AssertionError("must not be read")):
            state: dict = {"context_scope": json.dumps({"sources": ["standup"]})}
            seed_analysis_profile(state, "jira-PROJ")
        assert "analysis_profile_id" not in state and "custom_dod_items" not in state
