"""Tests for low-code detection wiring: analyzer reconciliation, intake
suggestions, the lighter-plan prompt clauses, rendering, and serialization.

See README: "Scrum Standards" — estimation; "Project Intake Questionnaire".
"""

import dataclasses
from dataclasses import asdict
from io import StringIO
from unittest.mock import MagicMock

from langchain_core.messages import HumanMessage
from rich.console import Console

from scrum_agent.agent.nodes import _apply_repo_signals, project_analyzer
from scrum_agent.agent.repo_signals import RepoSignals
from scrum_agent.agent.state import QuestionnaireState
from scrum_agent.formatters import render_analysis_panel
from scrum_agent.prompts.story_writer import get_story_writer_prompt
from scrum_agent.prompts.task_decomposer import get_task_decomposer_prompt
from scrum_agent.sessions import _dict_to_analysis
from tests._node_helpers import VALID_ANALYSIS_JSON, make_completed_questionnaire, make_dummy_analysis


def _render(panel) -> str:
    buf = StringIO()
    Console(file=buf, force_terminal=False, width=100, highlight=False).print(panel)
    return buf.getvalue()


def _mock_llm(monkeypatch, content: str):
    fake = MagicMock()
    fake.content = content
    llm = MagicMock()
    llm.invoke.return_value = fake
    monkeypatch.setattr("scrum_agent.agent.nodes.get_llm", lambda **kw: llm)


def _analyzer_state(description: str) -> dict:
    qs = make_completed_questionnaire()
    qs.answers[1] = description
    return {
        "messages": [HumanMessage(content="continue")],
        "questionnaire": qs,
        "team_size": 3,
        "velocity_per_sprint": 15,
    }


class TestAnalyzerReconciliation:
    """project_analyzer ORs the LLM verdict with the deterministic one."""

    def test_deterministic_marker_flips_low_code(self, monkeypatch):
        # LLM JSON has no is_low_code (→ False), but the description trips a marker.
        _mock_llm(monkeypatch, VALID_ANALYSIS_JSON)
        monkeypatch.setattr("scrum_agent.agent.nodes._scan_repo_context", lambda *a, **kw: (None, {}))
        result = project_analyzer(_analyzer_state("Build a Webflow + Zapier marketing site"))
        analysis = result["project_analysis"]
        assert analysis.is_low_code is True
        assert analysis.low_code_reason  # a reason was attached

    def test_llm_true_is_respected(self, monkeypatch):
        import json

        parsed = json.loads(VALID_ANALYSIS_JSON)
        parsed["is_low_code"] = True
        parsed["low_code_reason"] = "config-only integration"
        _mock_llm(monkeypatch, json.dumps(parsed))
        monkeypatch.setattr("scrum_agent.agent.nodes._scan_repo_context", lambda *a, **kw: (None, {}))
        # A plain description (no markers) — the flag must come from the LLM.
        result = project_analyzer(_analyzer_state("An internal reporting tool"))
        assert result["project_analysis"].is_low_code is True

    def test_ordinary_project_not_low_code(self, monkeypatch):
        _mock_llm(monkeypatch, VALID_ANALYSIS_JSON)
        monkeypatch.setattr("scrum_agent.agent.nodes._scan_repo_context", lambda *a, **kw: (None, {}))
        result = project_analyzer(_analyzer_state("A FastAPI backend with a React frontend"))
        assert result["project_analysis"].is_low_code is False

    def test_display_shows_low_code_notice(self, monkeypatch):
        _mock_llm(monkeypatch, VALID_ANALYSIS_JSON)
        monkeypatch.setattr("scrum_agent.agent.nodes._scan_repo_context", lambda *a, **kw: (None, {}))
        result = project_analyzer(_analyzer_state("A WordPress content site, no custom code"))
        assert "Low-code" in result["messages"][0].content


class TestApplyRepoSignals:
    """_apply_repo_signals stashes the scan and pre-fills Q11/Q12."""

    def _patch_scan(self, monkeypatch, signals: RepoSignals, raw="RAW"):
        monkeypatch.setattr(
            "scrum_agent.agent.nodes.scan_repo_signals",
            lambda qs: (raw, signals, {"status": "success"}),
        )

    def test_suggests_stack_and_integrations(self, monkeypatch):
        self._patch_scan(
            monkeypatch,
            RepoSignals(detected_stack=["TypeScript", "Next.js"], integrations=["Stripe"], source="github"),
        )
        qs = QuestionnaireState(intake_mode="smart")
        _apply_repo_signals(qs)
        assert qs.suggested_answers[11] == "TypeScript, Next.js"
        assert qs.answers[12] == "Stripe"
        assert qs._repo_context == "RAW"

    def test_stashes_low_code_verdict(self, monkeypatch):
        self._patch_scan(
            monkeypatch,
            RepoSignals(low_code=True, low_code_reasons=["mentions zapier (low-code ...)"]),
            raw="",
        )
        qs = QuestionnaireState(intake_mode="smart")
        _apply_repo_signals(qs)
        assert qs._repo_low_code is True
        assert "zapier" in qs._repo_low_code_reason

    def test_does_not_override_user_stack(self, monkeypatch):
        self._patch_scan(monkeypatch, RepoSignals(detected_stack=["Go"]))
        qs = QuestionnaireState(intake_mode="smart")
        qs.answers[11] = "Rust"  # user already answered
        _apply_repo_signals(qs)
        assert 11 not in qs.suggested_answers  # not suggested over a real answer

    def test_no_signals_is_noop(self, monkeypatch):
        self._patch_scan(monkeypatch, RepoSignals(), raw="")
        qs = QuestionnaireState(intake_mode="smart")
        _apply_repo_signals(qs)
        assert 11 not in qs.suggested_answers
        assert 12 not in qs.answers


class TestLowCodePrompts:
    """The lighter-plan clause appears only when is_low_code is True."""

    def _story_prompt(self, is_low_code: bool) -> str:
        return get_story_writer_prompt(
            "P", "desc", "greenfield", "goals", "users", "TS", "constraints", "features", is_low_code=is_low_code
        )

    def test_story_writer_includes_clause(self):
        assert "LOW-CODE" in self._story_prompt(True)

    def test_story_writer_omits_clause(self):
        assert "LOW-CODE" not in self._story_prompt(False)

    def test_task_decomposer_includes_clause(self):
        p = get_task_decomposer_prompt("P", "greenfield", "TS", "stories", is_low_code=True)
        assert "LOW-CODE" in p

    def test_task_decomposer_omits_clause(self):
        p = get_task_decomposer_prompt("P", "greenfield", "TS", "stories", is_low_code=False)
        assert "LOW-CODE" not in p


class TestLowCodeRender:
    def test_panel_shows_low_code_when_set(self):
        analysis = make_dummy_analysis(is_low_code=True, low_code_reason="Webflow site")
        out = _render(render_analysis_panel(analysis))
        assert "Low-code" in out
        assert "Webflow site" in out

    def test_panel_hides_low_code_when_unset(self):
        out = _render(render_analysis_panel(make_dummy_analysis()))
        assert "Low-code" not in out


class TestLowCodeSerialization:
    def test_round_trip_via_dict(self):
        analysis = make_dummy_analysis(is_low_code=True, low_code_reason="Zapier flow")
        restored = _dict_to_analysis(asdict(analysis))
        assert restored.is_low_code is True
        assert restored.low_code_reason == "Zapier flow"

    def test_missing_keys_default_false(self):
        # Old saved sessions predate the fields — reconstruction must not raise.
        d = asdict(make_dummy_analysis())
        d.pop("is_low_code", None)
        d.pop("low_code_reason", None)
        restored = _dict_to_analysis(d)
        assert restored.is_low_code is False
        assert restored.low_code_reason == ""

    def test_replace_keeps_defaults(self):
        # is_low_code has a default → frozen dataclass replace works for old shapes.
        base = make_dummy_analysis()
        assert dataclasses.replace(base, is_low_code=True).is_low_code is True
