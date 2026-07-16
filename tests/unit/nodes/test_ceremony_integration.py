"""Tests that ceremony history flows into the planning prompts, seeds the backlog,
and renders in the Analysis report — each section appears only when data is present.

See README: "Prompt Construction" — optional context sections.
"""

from unittest.mock import MagicMock

from langchain_core.messages import HumanMessage

from tests._node_helpers import VALID_ANALYSIS_JSON, make_completed_questionnaire
from yeaboi.agent.ceremony_history import CeremonyContext
from yeaboi.agent.nodes import project_analyzer
from yeaboi.prompts.analyzer import get_analyzer_prompt
from yeaboi.prompts.sprint_planner import get_sprint_planner_prompt
from yeaboi.prompts.story_writer import get_story_writer_prompt
from yeaboi.team_profile import TeamProfile
from yeaboi.team_profile_exporter import export_team_profile_md


class TestAnalyzerInjection:
    def test_section_present_when_history(self):
        p = get_analyzer_prompt("Q&A", 3, 15, ceremony_history="Open retro action items:\n- Fix CI")
        assert "Standup & Retro History" in p
        assert "Fix CI" in p

    def test_section_absent_when_empty(self):
        assert "Standup & Retro History" not in get_analyzer_prompt("Q&A", 3, 15)


class TestStoryWriterSeeding:
    def _prompt(self, items):
        return get_story_writer_prompt(
            "P", "d", "greenfield", "goals", "users", "TS", "constraints", "feats", carry_over_items=items
        )

    def test_carry_over_creates_retro_stories(self):
        p = self._prompt(("Fix flaky CI", "Add dashboards"))
        assert "Carry-over from Recent Retros" in p
        assert "[Retro]" in p
        assert "Fix flaky CI" in p

    def test_no_carry_over_no_section(self):
        assert "Carry-over from Recent Retros" not in self._prompt(())


class TestSprintPlannerInjection:
    def test_section_present(self):
        p = get_sprint_planner_prompt("P", "d", 20, 3, "stories", ceremony_history="70% confidence, declining")
        assert "Recent Standup & Retro Signals" in p
        assert "declining" in p

    def test_section_absent(self):
        assert "Recent Standup & Retro Signals" not in get_sprint_planner_prompt("P", "d", 20, 3, "stories")


class TestAnalysisExport:
    def _profile(self):
        return TeamProfile(team_id="jira-PROJ", source="jira", project_key="PROJ", sample_sprints=5, sample_stories=30)

    def _ceremony(self):
        return CeremonyContext(
            summary_md="x",
            retro_count=3,
            standup_count=8,
            retro_cadence="~every 2 week(s) (3 retros)",
            standup_cadence="roughly daily (8 standups)",
            confidence_trend="72% average confidence, improving",
            didnt_go_well_themes=(("Flaky CI", 3),),
            went_well_themes=(("Good pairing", 2),),
            action_items=("Fix CI",),
        )

    def test_md_includes_ceremony_section(self, tmp_path):
        path = export_team_profile_md(self._profile(), tmp_path, examples={}, ceremony=self._ceremony())
        text = path.read_text()
        assert "## Ceremony Cadence & Trends" in text
        assert "Retro cadence" in text
        assert "Flaky CI (3×)" in text
        assert "72% average confidence, improving" in text

    def test_md_omits_ceremony_when_absent(self, tmp_path):
        path = export_team_profile_md(self._profile(), tmp_path, examples={}, ceremony=None)
        assert "Ceremony Cadence" not in path.read_text()

    def test_md_omits_ceremony_when_empty(self, tmp_path):
        path = export_team_profile_md(self._profile(), tmp_path, examples={}, ceremony=CeremonyContext())
        assert "Ceremony Cadence" not in path.read_text()


class TestAnalyzerWiring:
    """project_analyzer gathers ceremony history, injects it, and stashes action items."""

    def test_action_items_stashed_and_injected(self, monkeypatch):
        captured = {}

        def _fake_prompt(*args, **kwargs):
            captured["ceremony_history"] = kwargs.get("ceremony_history", "")
            return "PROMPT"

        ctx = CeremonyContext(summary_md="Open retro action items:\n- Fix CI", action_items=("Fix CI",), retro_count=1)
        monkeypatch.setattr("yeaboi.agent.nodes.gather_ceremony_context", lambda *a, **k: ctx)
        monkeypatch.setattr("yeaboi.agent.nodes.get_analyzer_prompt", _fake_prompt)
        monkeypatch.setattr("yeaboi.agent.nodes._scan_repo_context", lambda *a, **k: (None, {}))
        fake = MagicMock()
        fake.content = VALID_ANALYSIS_JSON
        llm = MagicMock()
        llm.invoke.return_value = fake
        monkeypatch.setattr("yeaboi.agent.nodes.get_llm", lambda **kw: llm)

        state = {
            "messages": [HumanMessage(content="continue")],
            "questionnaire": make_completed_questionnaire(),
            "team_size": 3,
            "velocity_per_sprint": 15,
        }
        result = project_analyzer(state)
        assert result["_ceremony_action_items"] == ("Fix CI",)
        assert result["_ceremony_history"] == ctx.summary_md
        assert "Fix CI" in captured["ceremony_history"]
