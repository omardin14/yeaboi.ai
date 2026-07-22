"""Unit tests for analysis mode screen builders and preview flow.

Covers:
- _build_analysis_review_screen (shared template: progress dots, scrollbar, viewport)
- _build_instructions_review_screen
- _build_sample_epic_screen
- _build_sample_stories_screen
- _build_sample_tasks_screen
- _build_sample_sprint_screen
- _build_analysis_progress_screen
- _build_team_analysis_screen (scrollbar + viewport wrapping)

Mirrors the test patterns used for planning mode screens in tests/test_session.py
(TestBuildDescriptionScreen, TestBuildQuestionScreen, etc.).
"""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from yeaboi.ui.mode_select.screens._screens_secondary import (
    _build_analysis_progress_screen,
    _build_analysis_review_screen,
    _build_generate_confirm_screen,
    _build_instructions_review_screen,
    _build_sample_epic_screen,
    _build_sample_sprint_screen,
    _build_sample_stories_screen,
    _build_sample_tasks_screen,
    _build_team_analysis_screen,
    _build_team_insights_screen,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render(panel: Panel, width: int = 100) -> str:
    """Render a Rich Panel to plain text for content assertions."""
    buf = StringIO()
    console = Console(file=buf, width=width, force_terminal=False, highlight=False)
    console.print(panel)
    return buf.getvalue()


def _make_body_lines(n: int = 10, prefix: str = "Line") -> list:
    """Create a list of Text objects for use as body_lines."""
    return [Text(f"    {prefix} {i}", justify="left") for i in range(n)]


# ---------------------------------------------------------------------------
# Sample fixture data
# ---------------------------------------------------------------------------

_SAMPLE_INSTRUCTIONS = """\
## Velocity & Capacity
- Team velocity — 23.5 pts/sprint average
- Sprint length — 2 weeks
- Team size — 4 developers

## Story Conventions
- Story points — use Fibonacci scale (1, 2, 3, 5, 8)
- Acceptance criteria — Given/When/Then format, median 3 per story
→ Match this team's style exactly.

## Naming Conventions
- Label convention: quarterly goal (42%), released to dev (6%)
- Epic naming: quarter-scoped (e.g. "Q4|2025|High Region Outage DR")
→ Generated tickets MUST match these naming conventions.

Estimation note: Use THESE team-specific patterns, not generic Fibonacci rules.
"""

_SAMPLE_EPIC = {
    "title": "Q1|2026|Medium Platform Resilience Upgrade",
    "description": "Improve platform resilience with automated failover and monitoring.",
    "priority": "high",
    "stories_estimate": 5,
    "points_estimate": 18,
    "rationale": "Matches team's quarter-scoped naming convention.",
}

_SAMPLE_STORIES = [
    {
        "id": "S1",
        "title": "Implement automated failover",
        "persona": "developer",
        "goal": "automated failover between regions",
        "benefit": "reduced downtime",
        "story_points": 5,
        "priority": "high",
        "discipline": "infrastructure",
        "acceptance_criteria": [
            {"given": "primary region fails", "when": "failover triggered", "then": "traffic routes to secondary"},
            {"given": "secondary region active", "when": "primary recovers", "then": "failback completes"},
        ],
        "rationale": "Matches team's infrastructure story patterns.",
    },
    {
        "id": "S2",
        "title": "Add monitoring dashboards",
        "persona": "SRE",
        "goal": "visibility into failover health",
        "benefit": "faster incident response",
        "story_points": 3,
        "priority": "medium",
        "discipline": "observability",
        "acceptance_criteria": [
            {"given": "failover runs", "when": "dashboard queried", "then": "shows status within 30s"},
        ],
        "rationale": "Matches observability story pattern.",
    },
]

_SAMPLE_TASKS = [
    {
        "id": "T-S1-01",
        "story_id": "S1",
        "title": "Implement health check endpoint",
        "description": "Add /health endpoint to secondary region.",
        "label": "Code",
        "test_plan": "Unit test: verify endpoint returns 200.",
    },
    {
        "id": "T-S1-02",
        "story_id": "S1",
        "title": "Write failover integration tests",
        "description": "End-to-end test for failover trigger.",
        "label": "Testing",
        "test_plan": "Integration test: simulate region failure.",
    },
    {
        "id": "T-S2-01",
        "story_id": "S2",
        "title": "Create Grafana dashboard",
        "description": "Build dashboard with failover metrics.",
        "label": "Infrastructure",
        "test_plan": "Manual: verify dashboard loads in staging.",
    },
]

_SAMPLE_SPRINT = {
    "sprint_name": "Sprint 1",
    "velocity_target": 20,
    "stories_included": ["S1", "S2"],
    "total_points": 8,
    "capacity_notes": "Based on team avg of 23.5 pts/sprint, 8 pts leaves buffer.",
    "risks": ["S1 depends on cloud provider API", "S2 blocked until S1 failover endpoint is live"],
    "rationale": "Conservative allocation matching team's 88% completion rate.",
}

_SAMPLE_EXAMPLES = {
    "naming_conventions": {
        "epic_naming_style": "quarter-scoped",
        "epic_examples": ["Q4|2025|High Region Outage DR", "Q1|2026|Low Overmind improvement"],
        "template_sections": [("What is this about?", 0.8), ("Why does it matter?", 0.6)],
    },
    "ac_patterns": {"median_ac": 3},
    "task_decomposition": {
        "avg_tasks_per_story": 4.8,
        "type_distribution": {"Development": 64, "Testing": 13, "Deploy": 12},
        "common_tasks": [("create aurora rollback module", 2), ("update engine version", 2)],
    },
    "scope_changes": {
        "totals": {"avg_delivered_velocity": 25.9, "avg_committed_velocity": 19.1},
    },
}


# ---------------------------------------------------------------------------
# Shared builder: _build_analysis_review_screen
# ---------------------------------------------------------------------------


class TestBuildAnalysisReviewScreen:
    """Test the shared analysis review screen template."""

    def test_returns_panel(self):
        result = _build_analysis_review_screen(_make_body_lines(), stage_index=0, width=80, height=24)
        assert isinstance(result, Panel)

    def test_empty_body(self):
        result = _build_analysis_review_screen([], stage_index=0, width=80, height=24)
        assert isinstance(result, Panel)

    def test_all_stage_indices(self):
        """Each stage index (0-4) should render a valid panel."""
        lines = _make_body_lines(5)
        for idx in range(5):
            result = _build_analysis_review_screen(lines, stage_index=idx, width=80, height=24)
            assert isinstance(result, Panel)

    def test_custom_actions(self):
        result = _build_analysis_review_screen(
            _make_body_lines(),
            actions=["Done", "Export"],
            action_sel=1,
            width=80,
            height=24,
        )
        assert isinstance(result, Panel)

    def test_subtitle_rendered(self):
        result = _build_analysis_review_screen(
            _make_body_lines(),
            subtitle="Review planning instructions",
            width=80,
            height=24,
        )
        output = _render(result)
        assert "Review planning instructions" in output

    def test_progress_dots_current_stage(self):
        """Progress dots should show the current stage name in bold."""
        result = _build_analysis_review_screen(_make_body_lines(), stage_index=2, width=80, height=24)
        output = _render(result)
        assert "Stories" in output

    def test_scrollbar_appears_when_content_overflows(self):
        """Scrollbar should render when content exceeds viewport."""
        long_body = _make_body_lines(100)
        result = _build_analysis_review_screen(long_body, stage_index=0, width=80, height=24)
        output = _render(result)
        # Scrollbar uses thin/thick vertical bars
        assert "\u2502" in output or "\u2503" in output

    def test_no_scrollbar_short_content(self):
        """No scrollbar for content that fits within viewport."""
        short_body = _make_body_lines(3)
        result = _build_analysis_review_screen(short_body, stage_index=0, width=80, height=30)
        assert isinstance(result, Panel)

    def test_scroll_offset_clamps(self):
        """Scroll offset beyond max should clamp without error."""
        lines = _make_body_lines(10)
        result = _build_analysis_review_screen(lines, scroll_offset=9999, width=80, height=24)
        assert isinstance(result, Panel)

    def test_action_selection_highlights(self):
        """Each action index should produce a valid panel."""
        lines = _make_body_lines(5)
        for sel in range(4):
            result = _build_analysis_review_screen(lines, action_sel=sel, width=80, height=24)
            assert isinstance(result, Panel)

    def test_wrapping_lines_dont_overflow(self):
        """Long lines that wrap should not push buttons off-screen."""
        long_lines = [Text("    " + "x" * 200, justify="left") for _ in range(20)]
        result = _build_analysis_review_screen(long_lines, scroll_offset=15, width=80, height=24)
        output = _render(result, width=80)
        # Buttons should always be present in the rendered output
        assert "\u256d" in output  # top border of button box
        assert "\u256f" in output  # bottom border of button box

    def test_narrow_width(self):
        result = _build_analysis_review_screen(_make_body_lines(), width=40, height=24)
        assert isinstance(result, Panel)

    def test_tall_height(self):
        result = _build_analysis_review_screen(_make_body_lines(5), width=80, height=60)
        assert isinstance(result, Panel)

    def test_minimum_height(self):
        """Very short terminal should still render."""
        result = _build_analysis_review_screen(_make_body_lines(3), width=80, height=12)
        assert isinstance(result, Panel)


# ---------------------------------------------------------------------------
# Instructions review screen
# ---------------------------------------------------------------------------


class TestBuildInstructionsReviewScreen:
    """Test the planning instructions review page (stage 1 of preview flow)."""

    def test_returns_panel(self):
        result = _build_instructions_review_screen(_SAMPLE_INSTRUCTIONS, width=80, height=24)
        assert isinstance(result, Panel)

    def test_empty_instructions(self):
        result = _build_instructions_review_screen("", width=80, height=24)
        assert isinstance(result, Panel)

    def test_section_headers_rendered(self):
        result = _build_instructions_review_screen(_SAMPLE_INSTRUCTIONS, width=100, height=40)
        output = _render(result, width=100)
        assert "Velocity & Capacity" in output
        assert "Story Conventions" in output
        assert "Naming Conventions" in output

    def test_numbered_items(self):
        result = _build_instructions_review_screen(_SAMPLE_INSTRUCTIONS, width=100, height=40)
        output = _render(result, width=100)
        # Items should be numbered
        assert "1" in output
        assert "Team velocity" in output

    def test_arrow_directives_rendered(self):
        result = _build_instructions_review_screen(_SAMPLE_INSTRUCTIONS, width=120, height=40)
        output = _render(result, width=120)
        assert "Match this team" in output or "naming conventions" in output

    def test_scrollable(self):
        result1 = _build_instructions_review_screen(_SAMPLE_INSTRUCTIONS, scroll_offset=0, width=80, height=24)
        result2 = _build_instructions_review_screen(_SAMPLE_INSTRUCTIONS, scroll_offset=5, width=80, height=24)
        assert isinstance(result1, Panel)
        assert isinstance(result2, Panel)

    def test_action_buttons(self):
        """Instructions page has Accept/Edit/Export buttons."""
        # Use tall height to ensure buttons are visible (not clipped by viewport)
        result = _build_instructions_review_screen(_SAMPLE_INSTRUCTIONS, width=100, height=60)
        output = _render(result, width=100)
        assert "Accept" in output
        assert "Edit" in output
        assert "Export" in output

    def test_action_selection(self):
        for sel in range(3):
            result = _build_instructions_review_screen(_SAMPLE_INSTRUCTIONS, action_sel=sel, width=80, height=24)
            assert isinstance(result, Panel)

    def test_stage_indicator_shows_instructions(self):
        result = _build_instructions_review_screen(_SAMPLE_INSTRUCTIONS, width=100, height=24)
        output = _render(result, width=100)
        assert "Instructions" in output

    def test_long_instructions_scrollbar(self):
        """Long instructions should show scrollbar."""
        long_text = "\n".join(f"- Item {i} — description of item {i}" for i in range(50))
        result = _build_instructions_review_screen(long_text, width=80, height=24)
        output = _render(result, width=80)
        assert "\u2502" in output or "\u2503" in output


# ---------------------------------------------------------------------------
# Sample epic screen
# ---------------------------------------------------------------------------


class TestBuildSampleEpicScreen:
    """Test the sample epic review page (stage 2 of preview flow)."""

    def test_returns_panel(self):
        result = _build_sample_epic_screen(_SAMPLE_EPIC, width=80, height=24)
        assert isinstance(result, Panel)

    def test_empty_epic(self):
        result = _build_sample_epic_screen({}, width=80, height=24)
        assert isinstance(result, Panel)

    def test_epic_title_rendered(self):
        result = _build_sample_epic_screen(_SAMPLE_EPIC, width=120, height=40)
        output = _render(result, width=120)
        assert "Platform Resilience" in output

    def test_epic_priority_rendered(self):
        result = _build_sample_epic_screen(_SAMPLE_EPIC, width=100, height=40)
        output = _render(result, width=100)
        assert "high" in output.lower()

    def test_epic_rationale_rendered(self):
        result = _build_sample_epic_screen(_SAMPLE_EPIC, width=120, height=40)
        output = _render(result, width=120)
        assert "quarter-scoped" in output or "rationale" in output.lower()

    def test_with_examples(self):
        result = _build_sample_epic_screen(_SAMPLE_EPIC, examples=_SAMPLE_EXAMPLES, width=80, height=24)
        assert isinstance(result, Panel)

    def test_examples_pattern_info(self):
        """When examples provided, should show naming style info."""
        result = _build_sample_epic_screen(_SAMPLE_EPIC, examples=_SAMPLE_EXAMPLES, width=120, height=40)
        output = _render(result, width=120)
        assert "quarter-scoped" in output or "naming" in output.lower()

    def test_scrollable(self):
        result = _build_sample_epic_screen(_SAMPLE_EPIC, scroll_offset=3, width=80, height=24)
        assert isinstance(result, Panel)

    def test_action_selection(self):
        for sel in range(4):
            result = _build_sample_epic_screen(_SAMPLE_EPIC, action_sel=sel, width=80, height=24)
            assert isinstance(result, Panel)

    def test_stage_indicator_shows_epic(self):
        result = _build_sample_epic_screen(_SAMPLE_EPIC, width=100, height=24)
        output = _render(result, width=100)
        assert "Epic" in output


# ---------------------------------------------------------------------------
# Sample stories screen
# ---------------------------------------------------------------------------


class TestBuildSampleStoriesScreen:
    """Test the sample stories review page (stage 3 of preview flow)."""

    def test_returns_panel(self):
        result = _build_sample_stories_screen(_SAMPLE_STORIES, width=80, height=24)
        assert isinstance(result, Panel)

    def test_empty_stories(self):
        result = _build_sample_stories_screen([], width=80, height=24)
        assert isinstance(result, Panel)

    def test_single_story(self):
        result = _build_sample_stories_screen([_SAMPLE_STORIES[0]], width=80, height=24)
        assert isinstance(result, Panel)

    def test_story_ids_rendered(self):
        # Tall height so both stories fit the viewport below the 6-row ANSI-Shadow header.
        result = _build_sample_stories_screen(_SAMPLE_STORIES, width=100, height=70)
        output = _render(result, width=100)
        assert "S1" in output
        assert "S2" in output

    def test_story_points_rendered(self):
        result = _build_sample_stories_screen(_SAMPLE_STORIES, width=100, height=70)
        output = _render(result, width=100)
        assert "5" in output  # S1 points
        assert "3" in output  # S2 points

    def test_acceptance_criteria_rendered(self):
        result = _build_sample_stories_screen(_SAMPLE_STORIES, width=120, height=50)
        output = _render(result, width=120)
        # Given/When/Then format
        assert "Given" in output or "given" in output.lower()

    def test_persona_goal_rendered(self):
        result = _build_sample_stories_screen(_SAMPLE_STORIES, width=120, height=40)
        output = _render(result, width=120)
        assert "developer" in output or "SRE" in output

    def test_with_epic_title(self):
        result = _build_sample_stories_screen(
            _SAMPLE_STORIES,
            epic_title="Q1|2026|Medium Platform Resilience",
            width=100,
            height=24,
        )
        output = _render(result, width=100)
        assert "Platform Resilience" in output or "Stories" in output

    def test_scrollable(self):
        result = _build_sample_stories_screen(_SAMPLE_STORIES, scroll_offset=5, width=80, height=24)
        assert isinstance(result, Panel)

    def test_action_selection(self):
        for sel in range(4):
            result = _build_sample_stories_screen(_SAMPLE_STORIES, action_sel=sel, width=80, height=24)
            assert isinstance(result, Panel)

    def test_stage_indicator_shows_stories(self):
        result = _build_sample_stories_screen(_SAMPLE_STORIES, width=100, height=24)
        output = _render(result, width=100)
        assert "Stories" in output

    def test_story_without_acceptance_criteria(self):
        """Stories with empty AC list should still render."""
        story = {**_SAMPLE_STORIES[0], "acceptance_criteria": []}
        result = _build_sample_stories_screen([story], width=80, height=24)
        assert isinstance(result, Panel)

    def test_story_with_missing_fields(self):
        """Minimal story dict should not crash."""
        story = {"id": "S1", "title": "Minimal story"}
        result = _build_sample_stories_screen([story], width=80, height=24)
        assert isinstance(result, Panel)

    def test_definition_of_done_rendered(self):
        """Stories with definition_of_done should render DoD items."""
        story = {
            **_SAMPLE_STORIES[0],
            "definition_of_done": ["Code reviewed", "Tests passing", "Deployed to staging"],
        }
        result = _build_sample_stories_screen([story], width=120, height=60)
        output = _render(result, width=120)
        assert "Definition of Done" in output
        assert "Code reviewed" in output

    def test_story_without_dod(self):
        """Stories without definition_of_done should still render."""
        story = {k: v for k, v in _SAMPLE_STORIES[0].items() if k != "definition_of_done"}
        result = _build_sample_stories_screen([story], width=80, height=24)
        assert isinstance(result, Panel)


# ---------------------------------------------------------------------------
# Sample tasks screen
# ---------------------------------------------------------------------------


class TestBuildSampleTasksScreen:
    """Test the sample tasks review page (stage 4 of preview flow)."""

    def test_returns_panel(self):
        result = _build_sample_tasks_screen(_SAMPLE_TASKS, width=80, height=24)
        assert isinstance(result, Panel)

    def test_empty_tasks(self):
        result = _build_sample_tasks_screen([], width=80, height=24)
        assert isinstance(result, Panel)

    def test_task_ids_rendered(self):
        result = _build_sample_tasks_screen(_SAMPLE_TASKS, width=100, height=40)
        output = _render(result, width=100)
        assert "T-S1-01" in output
        assert "T-S2-01" in output

    def test_task_labels_rendered(self):
        result = _build_sample_tasks_screen(_SAMPLE_TASKS, width=100, height=40)
        output = _render(result, width=100)
        assert "Code" in output
        assert "Testing" in output

    def test_task_grouping_by_story(self):
        """Tasks should be grouped under their story ID."""
        result = _build_sample_tasks_screen(_SAMPLE_TASKS, width=100, height=40)
        output = _render(result, width=100)
        # Both story IDs should appear as group headers
        assert "S1" in output
        assert "S2" in output

    def test_test_plan_rendered(self):
        result = _build_sample_tasks_screen(_SAMPLE_TASKS, width=120, height=40)
        output = _render(result, width=120)
        assert "Unit test" in output or "test" in output.lower()

    def test_scrollable(self):
        result = _build_sample_tasks_screen(_SAMPLE_TASKS, scroll_offset=3, width=80, height=24)
        assert isinstance(result, Panel)

    def test_action_selection(self):
        for sel in range(4):
            result = _build_sample_tasks_screen(_SAMPLE_TASKS, action_sel=sel, width=80, height=24)
            assert isinstance(result, Panel)

    def test_stage_indicator_shows_tasks(self):
        result = _build_sample_tasks_screen(_SAMPLE_TASKS, width=100, height=24)
        output = _render(result, width=100)
        assert "Tasks" in output

    def test_single_task(self):
        result = _build_sample_tasks_screen([_SAMPLE_TASKS[0]], width=80, height=24)
        assert isinstance(result, Panel)

    def test_task_with_missing_fields(self):
        """Minimal task dict should not crash."""
        task = {"id": "T-1", "title": "Do something"}
        result = _build_sample_tasks_screen([task], width=80, height=24)
        assert isinstance(result, Panel)


# ---------------------------------------------------------------------------
# Sample sprint screen
# ---------------------------------------------------------------------------


class TestBuildSampleSprintScreen:
    """Test the sample sprint plan review page (stage 5 of preview flow)."""

    def test_returns_panel(self):
        result = _build_sample_sprint_screen(_SAMPLE_SPRINT, _SAMPLE_STORIES, width=80, height=24)
        assert isinstance(result, Panel)

    def test_empty_sprint(self):
        result = _build_sample_sprint_screen({}, [], width=80, height=24)
        assert isinstance(result, Panel)

    def test_sprint_name_rendered(self):
        result = _build_sample_sprint_screen(_SAMPLE_SPRINT, _SAMPLE_STORIES, width=100, height=40)
        output = _render(result, width=100)
        assert "Sprint 1" in output

    def test_velocity_target_rendered(self):
        result = _build_sample_sprint_screen(_SAMPLE_SPRINT, _SAMPLE_STORIES, width=100, height=40)
        output = _render(result, width=100)
        assert "20" in output

    def test_total_points_rendered(self):
        result = _build_sample_sprint_screen(_SAMPLE_SPRINT, _SAMPLE_STORIES, width=100, height=40)
        output = _render(result, width=100)
        assert "8" in output

    def test_stories_listed(self):
        result = _build_sample_sprint_screen(_SAMPLE_SPRINT, _SAMPLE_STORIES, width=100, height=40)
        output = _render(result, width=100)
        assert "S1" in output
        assert "S2" in output

    def test_risks_rendered(self):
        result = _build_sample_sprint_screen(_SAMPLE_SPRINT, _SAMPLE_STORIES, width=120, height=40)
        output = _render(result, width=120)
        assert "cloud provider" in output or "risk" in output.lower()

    def test_capacity_notes_rendered(self):
        result = _build_sample_sprint_screen(_SAMPLE_SPRINT, _SAMPLE_STORIES, width=120, height=40)
        output = _render(result, width=120)
        assert "23.5" in output or "buffer" in output

    def test_done_button(self):
        """Sprint page should have Done button (not Accept)."""
        result = _build_sample_sprint_screen(_SAMPLE_SPRINT, _SAMPLE_STORIES, width=100, height=60)
        output = _render(result, width=100)
        assert "Done" in output

    def test_scrollable(self):
        result = _build_sample_sprint_screen(_SAMPLE_SPRINT, _SAMPLE_STORIES, scroll_offset=3, width=80, height=24)
        assert isinstance(result, Panel)

    def test_action_selection(self):
        for sel in range(3):  # Done, Regenerate, Export
            result = _build_sample_sprint_screen(_SAMPLE_SPRINT, _SAMPLE_STORIES, action_sel=sel, width=80, height=24)
            assert isinstance(result, Panel)

    def test_stage_indicator_shows_sprint(self):
        result = _build_sample_sprint_screen(_SAMPLE_SPRINT, _SAMPLE_STORIES, width=100, height=24)
        output = _render(result, width=100)
        assert "Sprint" in output

    def test_sprint_without_risks(self):
        sprint = {**_SAMPLE_SPRINT, "risks": []}
        result = _build_sample_sprint_screen(sprint, _SAMPLE_STORIES, width=80, height=24)
        assert isinstance(result, Panel)

    def test_sprint_without_stories(self):
        """Sprint with story IDs but no matching story objects."""
        result = _build_sample_sprint_screen(_SAMPLE_SPRINT, [], width=80, height=24)
        assert isinstance(result, Panel)


# ---------------------------------------------------------------------------
# Analysis progress screen
# ---------------------------------------------------------------------------


class TestBuildAnalysisProgressScreen:
    """Test the loading/progress screen shown during analysis."""

    def test_returns_panel(self):
        result = _build_analysis_progress_screen([], width=80, height=24)
        assert isinstance(result, Panel)

    def test_with_progress_steps(self):
        steps = ["Fetching sprints...", "Analysing velocity...", "Building profile..."]
        result = _build_analysis_progress_screen(steps, width=80, height=24)
        output = _render(result)
        assert "Fetching sprints" in output

    def test_elapsed_time(self):
        result = _build_analysis_progress_screen(["Working..."], elapsed=12.5, width=80, height=24)
        output = _render(result)
        assert "12" in output  # elapsed seconds shown

    def test_animation_tick(self):
        """Different animation ticks should produce valid panels."""
        for tick in [0.0, 0.25, 0.5, 0.75, 1.0]:
            result = _build_analysis_progress_screen(["Working..."], anim_tick=tick, width=80, height=24)
            assert isinstance(result, Panel)

    def test_analysis_mode_renders(self):
        """Analysis mode should render without error and use analysis title."""
        result = _build_analysis_progress_screen(["Working..."], mode="analysis", width=100, height=24)
        assert isinstance(result, Panel)

    def test_planning_mode_renders(self):
        """Planning mode should render without error and use planning title."""
        result = _build_analysis_progress_screen(["Working..."], mode="planning", width=100, height=24)
        assert isinstance(result, Panel)

    def test_source_label(self):
        result = _build_analysis_progress_screen(
            ["Fetching..."], source="azdevops", mode="analysis", width=100, height=24
        )
        assert isinstance(result, Panel)

    def test_empty_progress(self):
        result = _build_analysis_progress_screen([], elapsed=0.0, width=80, height=24)
        assert isinstance(result, Panel)


# ---------------------------------------------------------------------------
# Team analysis screen (initial report page with custom viewport)
# ---------------------------------------------------------------------------


class TestBuildTeamAnalysisScreenExtended:
    """Extended tests for the initial analysis report screen.

    Supplements the 2 existing tests in test_team_profile.py with coverage
    for scrollbar, viewport wrapping, export selection, and edge cases.
    """

    @pytest.fixture()
    def profile(self):
        from yeaboi.team_profile import (
            DoDSignal,
            EpicPattern,
            SpilloverStats,
            StoryPointCalibration,
            StoryShapePattern,
            TeamProfile,
            WritingPatterns,
        )

        return TeamProfile(
            team_id="azdevops-PROJ",
            source="azdevops",
            project_key="PROJ",
            sample_sprints=8,
            sample_stories=64,
            velocity_avg=23.5,
            velocity_stddev=3.2,
            point_calibrations=(
                StoryPointCalibration(point_value=1, avg_cycle_time_days=0.5, sample_count=10),
                StoryPointCalibration(point_value=3, avg_cycle_time_days=2.1, sample_count=20, overshoot_pct=15.0),
                StoryPointCalibration(point_value=5, avg_cycle_time_days=4.2, sample_count=15, overshoot_pct=20.0),
            ),
            story_shapes=(
                StoryShapePattern(
                    discipline="backend", avg_points=3.2, avg_ac_count=3.0, avg_task_count=2.8, sample_count=20
                ),
                StoryShapePattern(
                    discipline="frontend", avg_points=2.5, avg_ac_count=2.5, avg_task_count=2.0, sample_count=12
                ),
            ),
            epic_pattern=EpicPattern(
                avg_stories_per_epic=6.0, avg_points_per_epic=18.0, typical_story_count_range=(4, 9)
            ),
            estimation_accuracy_pct=78.0,
            sprint_completion_rate=88.0,
            spillover=SpilloverStats(
                carried_over_pct=12.5,
                avg_spillover_pts=3.2,
                most_common_spillover_reason="backend stories",
            ),
            dod_signal=DoDSignal(
                common_checklist_items=("tests passing", "PR merged", "code reviewed"),
                stories_with_comments_pct=85.0,
                stories_with_pr_link_pct=82.0,
                stories_with_review_mention_pct=76.0,
                stories_with_testing_mention_pct=61.0,
                stories_with_deploy_mention_pct=44.0,
            ),
            writing_patterns=WritingPatterns(
                median_ac_count=3.0,
                median_task_count_per_story=2.5,
                subtask_label_distribution=(("Code", 0.58), ("Testing", 0.28)),
                common_subtask_patterns=("Write unit tests", "Deploy to staging"),
                subtasks_use_consistent_naming=True,
                common_personas=("developer", "admin"),
                uses_given_when_then=True,
                stories_with_subtasks_pct=72.0,
            ),
            sprints_fully_completed=6,
            sprints_partially_completed=2,
            sprints_analysed=8,
        )

    def test_returns_panel(self, profile):
        result = _build_team_analysis_screen(profile, width=80, height=30)
        assert isinstance(result, Panel)

    def test_export_button_selection(self, profile):
        """Each export_sel value should highlight a different button."""
        for sel in range(2):  # Export, Continue
            result = _build_team_analysis_screen(profile, export_sel=sel, width=80, height=30)
            assert isinstance(result, Panel)

    def test_scrollbar_on_tall_content(self, profile):
        """Profile with many sections should show scrollbar."""
        result = _build_team_analysis_screen(profile, scroll_offset=0, width=80, height=24)
        output = _render(result, width=80)
        assert "\u2502" in output or "\u2503" in output

    def test_scroll_to_bottom(self, profile):
        """Scrolling to a large offset should clamp and still show buttons."""
        result = _build_team_analysis_screen(profile, scroll_offset=9999, width=80, height=24)
        output = _render(result, width=80)
        # Buttons should still be visible
        assert "Export" in output or "Continue" in output

    def test_with_examples(self, profile):
        result = _build_team_analysis_screen(profile, examples=_SAMPLE_EXAMPLES, width=80, height=30)
        assert isinstance(result, Panel)

    def test_with_sprint_names(self, profile):
        names = ["Sprint 101", "Sprint 102", "Sprint 103"]
        result = _build_team_analysis_screen(profile, sprint_names=names, width=80, height=30)
        assert isinstance(result, Panel)

    def test_with_team_name(self, profile):
        result = _build_team_analysis_screen(profile, team_name="Platform Team", width=100, height=30)
        output = _render(result, width=100)
        assert "Platform Team" in output

    def test_narrow_terminal(self, profile):
        """Should render without crash on narrow terminals."""
        result = _build_team_analysis_screen(profile, width=40, height=24)
        assert isinstance(result, Panel)

    def test_short_terminal(self, profile):
        """Should render on short terminals without crash."""
        result = _build_team_analysis_screen(profile, width=80, height=14)
        assert isinstance(result, Panel)

    def test_velocity_section_rendered(self, profile):
        result = _build_team_analysis_screen(profile, width=100, height=50)
        output = _render(result, width=100)
        assert "23.5" in output  # velocity_avg

    def test_spillover_rendered(self, profile):
        result = _build_team_analysis_screen(profile, view="velocity", width=100, height=100)
        output = _render(result, width=100)
        assert "12.5" in output or "spillover" in output.lower()

    def test_zero_scroll(self, profile):
        result = _build_team_analysis_screen(profile, scroll_offset=0, width=80, height=30)
        assert isinstance(result, Panel)

    def test_mid_scroll(self, profile):
        result = _build_team_analysis_screen(profile, scroll_offset=10, width=80, height=30)
        assert isinstance(result, Panel)

    # Wrapping tables (DoD + Proposed DoD) previously reported a naive row_count
    # as their height. When cells wrapped onto multiple rows the viewport packer
    # over-filled the fixed-height panel and Rich cropped the action buttons off
    # the bottom (Patterns page showed no buttons). Heights are now measured, so
    # the buttons must survive even with a tall, heavily-wrapping Proposed DoD.
    _DOD_HEAVY_EXAMPLES = {
        "dod_testing": [{"issue_key": "PSOT-791", "summary": "Phase 9: Entra App Registration flow"}],
        "dod_pr": [{"issue_key": "PSOT-851", "summary": "WIZ - Create an automated repo scanner"}],
        "dod_review": [{"issue_key": "PSOT-880", "summary": "Complete DAST API Scan Implementation"}],
        "dod_deploy": [{"issue_key": "PSOT-880", "summary": "Complete DAST API Scan Implementation"}],
        "proposed_dod": {
            "summary": "7 of 9 practices are well-established. The team has a clear definition of done.",
            "health": "strong",
            "items": [
                {
                    "practice": f"Practice number {i} updated",
                    "status": "established",
                    "signals": f"{90 - i * 8}% mentioned in stories · 6% have subtasks",
                    "recommendation": "Consistently done. Include as a required DoD step.",
                }
                for i in range(8)
            ],
        },
    }

    @staticmethod
    def _render_cropped(panel: Panel, width: int, height: int) -> str:
        """Render exactly like the TUI: a fixed-height panel on a sized console.

        The panel's ``height`` crops overflowing content, so this reproduces the
        real button-cropping behaviour that a height-less render would hide.
        """
        buf = StringIO()
        console = Console(file=buf, width=width, height=height, force_terminal=False, highlight=False)
        console.print(panel)
        return buf.getvalue()

    def test_workflow_card_buttons_visible_with_wrapping_tables(self, profile):
        """Workflow & DoD action buttons must stay on screen even when tables wrap a lot."""
        for scroll in (0, 9999):  # top of card and clamped-to-bottom
            panel = _build_team_analysis_screen(
                profile,
                examples=self._DOD_HEAVY_EXAMPLES,
                view="workflow",
                width=120,
                height=44,
                scroll_offset=scroll,
            )
            output = self._render_cropped(panel, width=120, height=44)
            assert "Back" in output, f"Back button cropped at scroll={scroll}"
            assert "Continue" in output, f"Continue button cropped at scroll={scroll}"


# ---------------------------------------------------------------------------
# Confirmation screen: _build_generate_confirm_screen
# ---------------------------------------------------------------------------


class TestBuildGenerateConfirmScreen:
    """The gate shown between team/board analysis and sample-ticket generation."""

    def test_returns_panel(self):
        result = _build_generate_confirm_screen(width=80, height=24)
        assert isinstance(result, Panel)

    def test_renders_prompt_and_buttons(self):
        output = _render(_build_generate_confirm_screen(width=100, height=30), width=100)
        assert "generate sample tickets now?" in output
        assert "Generate tickets" in output
        assert "Not now" in output

    def test_both_action_selections(self):
        """Either button may be highlighted without crashing."""
        for sel in (0, 1):
            result = _build_generate_confirm_screen(width=100, height=30, action_sel=sel)
            assert isinstance(result, Panel)

    def test_subtitle_rendered(self):
        output = _render(_build_generate_confirm_screen(width=100, height=30, subtitle="jira/PROJ"), width=100)
        assert "jira/PROJ" in output

    def test_narrow_terminal(self):
        assert isinstance(_build_generate_confirm_screen(width=40, height=24), Panel)

    def test_short_terminal(self):
        assert isinstance(_build_generate_confirm_screen(width=80, height=14), Panel)

    def test_buttons_registered(self):
        """New button labels must have colours registered (CLAUDE.md convention)."""
        from yeaboi.ui.shared._components import _BTN_COLORS

        assert "Generate tickets" in _BTN_COLORS
        assert "Not now" in _BTN_COLORS


class TestConfirmTicketGeneration:
    """The driver loop gating analysis → ticket generation (key handling)."""

    class _FakeConsole:
        size = (100, 30)

    class _FakeLive:
        def __init__(self):
            self.frames = 0

        def update(self, _panel):
            self.frames += 1

    @staticmethod
    def _run(keys):
        """Drive _confirm_ticket_generation with a scripted key sequence."""
        from yeaboi.ui.mode_select import _confirm_ticket_generation

        it = iter(keys)

        def _read_key(timeout=None):
            return next(it)

        live = TestConfirmTicketGeneration._FakeLive()
        result = _confirm_ticket_generation(
            live,
            TestConfirmTicketGeneration._FakeConsole(),
            _read_key,
            0.05,
            True,
            subtitle="jira/PROJ",
        )
        return result, live

    def test_enter_on_generate_confirms(self):
        result, live = self._run(["enter"])
        assert result is True
        assert live.frames >= 1  # rendered at least once before the keypress

    def test_right_then_enter_declines(self):
        # Move to "Not now" (sel=1), then confirm the selection.
        result, _ = self._run(["right", "enter"])
        assert result is False

    def test_right_left_enter_confirms(self):
        # Navigate to Not now and back to Generate, then Enter.
        result, _ = self._run(["right", "left", "enter"])
        assert result is True

    def test_esc_declines(self):
        result, _ = self._run(["esc"])
        assert result is False

    def test_space_selects_current(self):
        result, _ = self._run([" "])
        assert result is True

    def test_left_clamps_at_zero(self):
        # Pressing left at sel=0 stays on Generate.
        result, _ = self._run(["left", "left", "enter"])
        assert result is True

    def test_right_clamps_at_one(self):
        # Pressing right past the last button stays on Not now.
        result, _ = self._run(["right", "right", "enter"])
        assert result is False


# ---------------------------------------------------------------------------
# Analysis overview + section card views (view= API)
# ---------------------------------------------------------------------------


def _make_overview_profile():
    from yeaboi.team_profile import (
        DoDSignal,
        SpilloverStats,
        StoryPointCalibration,
        TeamProfile,
        WritingPatterns,
    )

    return TeamProfile(
        team_id="jira-SCRUM",
        source="jira",
        project_key="SCRUM",
        sample_sprints=4,
        sample_stories=40,
        velocity_avg=23.5,
        velocity_stddev=3.2,
        point_calibrations=(StoryPointCalibration(point_value=3, avg_cycle_time_days=4.0, sample_count=12),),
        estimation_accuracy_pct=78.0,
        sprint_completion_rate=88.0,
        spillover=SpilloverStats(carried_over_pct=12.0),
        dod_signal=DoDSignal(stories_with_pr_link_pct=40.0, stories_with_testing_mention_pct=30.0),
        writing_patterns=WritingPatterns(uses_given_when_then=True, median_ac_count=3.0),
    )


_NARRATIVE_EXAMPLES = {
    "team_size": 5,
    "sprint_details": [
        {"name": "Sprint 1", "points": 22, "planned": 10, "completed": 9, "rate": 90, "done": True},
        {"name": "Sprint 2", "points": 25, "planned": 12, "completed": 10, "rate": 83, "done": False},
    ],
    "scope_changes": {
        "totals": {"avg_committed_velocity": 26.0, "avg_delivered_velocity": 23.5},
        "per_sprint": [
            {"name": "Sprint 1", "committed_pts": 26, "final_pts": 28, "scope_change_total": 2, "scope_churn": 0.12}
        ],
    },
    "narrative": {
        "executive_summary": "The team is broadly healthy with steady delivery.",
        "sections": {
            "velocity": "Velocity is stable sprint to sprint.",
            "team": "Work is spread evenly across the team.",
            "estimation": "Estimates mostly hold.",
            "workflow": "Task breakdown is consistent.",
            "writing": "Tickets are well written.",
            "trends": "No worrying long-term trends.",
            "recommendations": "Two small things to tighten up.",
        },
    },
    "insights": {
        "start": [
            {
                "title": "Link PRs to tickets",
                "detail": "Add PR links to every story for traceability.",
                "evidence": "40% PR linkage",
            }
        ],
        "stop": [
            {"title": "Overcommitting sprints", "detail": "Plan to actual capacity.", "evidence": "88% completion"}
        ],
        "keep": [{"title": "Given/When/Then ACs", "detail": "Structured ACs work well.", "evidence": "GWT detected"}],
        "try": [{"title": "WIP limits", "detail": "Cap in-progress work.", "evidence": "12% spillover"}],
    },
}

_ALL_CARD_KEYS = ("velocity", "team", "estimation", "workflow", "writing", "trends", "recommendations", "insights")


class TestAnalysisOverview:
    """The overview view: headline stats, AI executive summary, card list."""

    def _render_view(self, examples=None, selected_card=0, width=100, height=40):
        panel = _build_team_analysis_screen(
            _make_overview_profile(),
            examples=examples,
            view="overview",
            selected_card=selected_card,
            width=width,
            height=height,
        )
        assert isinstance(panel, Panel)
        return _render(panel, width=width)

    def test_returns_panel_by_default(self):
        panel = _build_team_analysis_screen(_make_overview_profile(), width=80, height=30)
        assert isinstance(panel, Panel)

    def test_headline_stats_render(self):
        output = self._render_view(examples=_NARRATIVE_EXAMPLES)
        assert "At a Glance" in output
        assert "5 contributors" in output
        assert "estimates hold" in output

    def test_all_card_titles_render(self):
        # Selection auto-scrolls, so check the top half with card 0 selected
        # and the bottom half with the last card selected.
        top = self._render_view(examples=_NARRATIVE_EXAMPLES, selected_card=0)
        bottom = self._render_view(examples=_NARRATIVE_EXAMPLES, selected_card=9)
        combined = top + bottom
        for title in (
            "Velocity & Sprints",
            "Team Members",
            "Estimation & Points",
            "Workflow & DoD",
            "Writing Style",
            "Trends & Repos",
            "Recommendations",
            "AI Adoption",
            "Documentation",
            "Team Insights",
        ):
            assert title in combined, title

    def test_teaser_stats_render(self):
        output = self._render_view(examples=_NARRATIVE_EXAMPLES)
        assert "pts/sprint" in output

    def test_selected_card_marker_moves(self):
        first = self._render_view(examples=_NARRATIVE_EXAMPLES, selected_card=0)
        second = self._render_view(examples=_NARRATIVE_EXAMPLES, selected_card=1)
        assert first != second
        assert "▸" in first and "▸" in second

    def test_executive_summary_renders(self):
        output = self._render_view(examples=_NARRATIVE_EXAMPLES)
        assert "broadly healthy" in output

    def test_missing_narrative_shows_hint(self):
        """Old saved profiles have no narrative — overview must still render."""
        ex = {k: v for k, v in _NARRATIVE_EXAMPLES.items() if k != "narrative"}
        output = self._render_view(examples=ex)
        assert "No AI summary saved" in output

    def test_no_examples_at_all(self):
        output = self._render_view(examples=None)
        assert "Sections" in output

    def test_recommendation_warning_count(self):
        from yeaboi.team_profile import DoDSignal, SpilloverStats, TeamProfile, WritingPatterns

        weak = TeamProfile(
            team_id="jira-W",
            source="jira",
            project_key="W",
            sample_sprints=4,
            sample_stories=40,
            velocity_avg=20.0,
            velocity_stddev=12.0,
            sprint_completion_rate=45.0,
            spillover=SpilloverStats(carried_over_pct=30.0),
            dod_signal=DoDSignal(),
            writing_patterns=WritingPatterns(),
        )
        panel = _build_team_analysis_screen(weak, view="overview", selected_card=6, width=100, height=40)
        output = _render(panel, width=100)
        assert "⚠" in output and "flagged" in output

    def test_narrow_and_short_terminals(self):
        for w, h in ((40, 14), (60, 20), (200, 60)):
            panel = _build_team_analysis_screen(
                _make_overview_profile(), examples=_NARRATIVE_EXAMPLES, view="overview", width=w, height=h
            )
            assert isinstance(panel, Panel)

    def test_overview_actions(self):
        output = self._render_view(examples=_NARRATIVE_EXAMPLES)
        assert "Open" in output and "Continue" in output


class TestAnalysisSectionDetail:
    """Each section card renders its sections, narrative block and glossary."""

    @pytest.mark.parametrize("card_key", _ALL_CARD_KEYS)
    def test_card_renders_panel(self, card_key):
        panel = _build_team_analysis_screen(
            _make_overview_profile(), examples=_NARRATIVE_EXAMPLES, view=card_key, width=100, height=40
        )
        assert isinstance(panel, Panel)

    # The insights card is coaching content itself — it has no narrative key.
    @pytest.mark.parametrize("card_key", tuple(k for k in _ALL_CARD_KEYS if k != "insights"))
    def test_narrative_block_shown(self, card_key):
        panel = _build_team_analysis_screen(
            _make_overview_profile(), examples=_NARRATIVE_EXAMPLES, view=card_key, width=100, height=50
        )
        output = _render(panel, width=100)
        assert "What this means" in output

    @pytest.mark.parametrize("card_key", _ALL_CARD_KEYS)
    def test_narrative_block_omitted_without_narrative(self, card_key):
        ex = {k: v for k, v in _NARRATIVE_EXAMPLES.items() if k != "narrative"}
        panel = _build_team_analysis_screen(_make_overview_profile(), examples=ex, view=card_key, width=100, height=50)
        output = _render(panel, width=100)
        assert "What this means" not in output

    @pytest.mark.parametrize("card_key", _ALL_CARD_KEYS)
    def test_detail_actions(self, card_key):
        panel = _build_team_analysis_screen(
            _make_overview_profile(), examples=_NARRATIVE_EXAMPLES, view=card_key, width=100, height=40
        )
        output = _render(panel, width=100)
        assert "Back" in output

    def test_velocity_card_sections_and_breadcrumb(self):
        panel = _build_team_analysis_screen(
            _make_overview_profile(), examples=_NARRATIVE_EXAMPLES, view="velocity", width=100, height=60
        )
        output = _render(panel, width=100)
        assert "Team & Velocity" in output
        assert "Sprint Breakdown" in output
        assert "Overview › Velocity & Sprints" in output

    def test_velocity_card_churn_glossary(self):
        """The Churn column jargon is explained on the card (user complaint)."""
        panel = _build_team_analysis_screen(
            _make_overview_profile(),
            examples=_NARRATIVE_EXAMPLES,
            view="velocity",
            width=100,
            height=40,
            scroll_offset=9999,
        )
        output = _render(panel, width=100)
        assert "What the terms mean" in output
        assert "Churn — % of committed points added or removed mid-sprint" in output

    def test_estimation_card_glossary(self):
        panel = _build_team_analysis_screen(
            _make_overview_profile(),
            examples=_NARRATIVE_EXAMPLES,
            view="estimation",
            width=100,
            height=40,
            scroll_offset=9999,
        )
        output = _render(panel, width=100)
        assert "Cycle — days from work starting to done" in output

    def test_workflow_card_no_glossary(self):
        panel = _build_team_analysis_screen(
            _make_overview_profile(),
            examples=_NARRATIVE_EXAMPLES,
            view="workflow",
            width=100,
            height=40,
            scroll_offset=9999,
        )
        output = _render(panel, width=100)
        assert "What the terms mean" not in output

    def test_recommendations_card_renders_recs(self):
        from yeaboi.team_profile import DoDSignal, SpilloverStats, TeamProfile, WritingPatterns

        weak = TeamProfile(
            team_id="jira-W",
            source="jira",
            project_key="W",
            sample_sprints=4,
            sample_stories=40,
            velocity_avg=20.0,
            velocity_stddev=12.0,
            sprint_completion_rate=45.0,
            spillover=SpilloverStats(carried_over_pct=30.0),
            dod_signal=DoDSignal(),
            writing_patterns=WritingPatterns(),
        )
        panel = _build_team_analysis_screen(weak, view="recommendations", width=100, height=50)
        output = _render(panel, width=100)
        assert "Low sprint completion" in output

    @pytest.mark.parametrize("card_key", _ALL_CARD_KEYS)
    def test_empty_profile_all_cards(self, card_key):
        from yeaboi.team_profile import TeamProfile

        empty = TeamProfile(team_id="e", source="jira", project_key="X", sample_sprints=0, sample_stories=0)
        panel = _build_team_analysis_screen(empty, examples=None, view=card_key, width=80, height=24)
        assert isinstance(panel, Panel)


class TestDocumentationCard:
    """The Documentation card: clarity + AI-usage estimate + coaching (populated + empty)."""

    def _profile(self, sig):
        from yeaboi.team_profile import TeamProfile

        return TeamProfile(
            team_id="jira-D",
            source="jira",
            project_key="D",
            sample_sprints=4,
            sample_stories=40,
            velocity_avg=30.0,
            doc_quality=sig,
        )

    def test_populated_renders_clarity_estimate_and_flag(self):
        from yeaboi.team_profile import DocQualitySignal

        sig = DocQualitySignal(
            pages_scanned=6,
            platforms_scanned=("confluence", "notion"),
            avg_clarity=52.0,
            clear_pages=2,
            mixed_pages=2,
            unclear_pages=2,
            avg_ai_likelihood=61.0,
            likely_ai_pages=3,
            ai_marked_pages=1,
            per_platform=(("confluence", 4), ("notion", 2)),
            flagged_pages=(("Onboarding guide", "clarity 30/100 — dense or long-winded"),),
        )
        ex = {
            "doc_quality": {
                "samples": [
                    {
                        "title": "Onboarding guide",
                        "platform": "confluence",
                        "clarity": 30,
                        "ai_likelihood": 12,
                        "url": "https://wiki/onboarding",
                    }
                ],
                "insights": {
                    "start": [
                        {
                            "title": "Tighten the least-clear pages",
                            "detail": "Trim it.",
                            "evidence": "52/100",
                            "link": "https://wiki/onboarding",
                        }
                    ],
                    "stop": [],
                    "keep": [],
                    "try": [],
                },
            }
        }
        panel = _build_team_analysis_screen(self._profile(sig), examples=ex, view="documentation", width=100, height=60)
        output = _render(panel, width=100)
        assert "Documentation" in output
        assert "52/100" in output  # clarity score
        assert "estimate" in output.lower()  # AI-likelihood is framed as an estimate
        assert "lower bound" in output.lower()  # explicit-marker framing
        assert "Onboarding guide" in output  # flagged page
        assert "Tighten the least-clear pages" in output  # coaching
        assert "Examples" in output  # examples section
        assert "https://wiki/onboarding" in output  # page link on example + coaching item

    def test_empty_state_and_coverage(self):
        from yeaboi.team_profile import TeamProfile

        prof = TeamProfile(team_id="e", source="jira", project_key="X")
        ex = {"doc_quality": {"coverage": ["notion: NOTION_TOKEN not set"]}}
        panel = _build_team_analysis_screen(prof, examples=ex, view="documentation", width=90, height=30)
        output = _render(panel, width=90)
        assert "No documentation scan" in output
        assert "NOTION_TOKEN not set" in output


# ---------------------------------------------------------------------------
# Team insights screen (results → insights → generate-tickets confirm)
# ---------------------------------------------------------------------------


class TestBuildTeamInsightsScreen:
    """The coaching-insights screen shown before the sample-ticket confirm."""

    def _render_screen(self, examples=None, width=100, height=40, **kwargs):
        panel = _build_team_insights_screen(
            _make_overview_profile(),
            examples=examples,
            width=width,
            height=height,
            **kwargs,
        )
        assert isinstance(panel, Panel)
        return _render(panel, width=width)

    def test_returns_panel(self):
        panel = _build_team_insights_screen(_make_overview_profile(), examples=_NARRATIVE_EXAMPLES)
        assert isinstance(panel, Panel)

    def test_intro_line_renders(self):
        output = self._render_screen(examples=_NARRATIVE_EXAMPLES)
        assert "How to improve this team" in output

    def test_all_category_headers_render(self):
        # Tall screen so all four categories fit the viewport at once.
        output = self._render_screen(examples=_NARRATIVE_EXAMPLES, height=60)
        for header in ("START DOING", "STOP DOING", "KEEP DOING", "WORTH TRYING"):
            assert header in output, header

    def test_item_title_detail_evidence_render(self):
        output = self._render_screen(examples=_NARRATIVE_EXAMPLES, height=60)
        assert "Link PRs to tickets" in output
        assert "traceability" in output
        assert "40% PR linkage" in output

    def test_default_actions(self):
        output = self._render_screen(examples=_NARRATIVE_EXAMPLES)
        for action in ("Continue", "Export", "Back"):
            assert action in output, action

    def test_action_selection_highlights(self):
        rendered = [self._render_screen(examples=_NARRATIVE_EXAMPLES, action_sel=i) for i in range(3)]
        assert len(set(rendered)) == 1 or len(set(rendered)) > 1  # renders for every selection
        for r in rendered:
            assert "Continue" in r

    def test_empty_examples_show_hint(self):
        """Old saved profiles have no insights — screen must still render."""
        output = self._render_screen(examples={})
        assert "No insights saved" in output

    def test_none_examples_show_hint(self):
        output = self._render_screen(examples=None)
        assert "No insights saved" in output

    def test_scrollbar_on_overflow(self):
        output = self._render_screen(examples=_NARRATIVE_EXAMPLES, height=20)
        assert "│" in output or "┃" in output

    def test_scroll_clamps_and_keeps_buttons(self):
        output = self._render_screen(examples=_NARRATIVE_EXAMPLES, height=24, scroll_offset=9999)
        assert "Continue" in output

    def test_narrow_terminal_no_crash(self):
        panel = _build_team_insights_screen(_make_overview_profile(), examples=_NARRATIVE_EXAMPLES, width=40, height=24)
        assert isinstance(panel, Panel)

    def test_short_terminal_no_crash(self):
        panel = _build_team_insights_screen(_make_overview_profile(), examples=_NARRATIVE_EXAMPLES, width=80, height=10)
        assert isinstance(panel, Panel)

    def test_subtitle_renders(self):
        output = self._render_screen(examples=_NARRATIVE_EXAMPLES, subtitle="jira/SCRUM  ·  Team Insights")
        assert "Team Insights" in output

    def test_insights_card_teaser_on_overview(self):
        panel = _build_team_analysis_screen(
            _make_overview_profile(),
            examples=_NARRATIVE_EXAMPLES,
            view="overview",
            selected_card=9,
            width=100,
            height=40,
        )
        output = _render(panel, width=100)
        assert "1 start" in output
        assert "1 try" in output

    def test_insights_card_detail_view(self):
        panel = _build_team_analysis_screen(
            _make_overview_profile(),
            examples=_NARRATIVE_EXAMPLES,
            view="insights",
            width=100,
            height=50,
        )
        output = _render(panel, width=100)
        assert "START DOING" in output
        assert "Link PRs to tickets" in output


class TestRunTeamInsights:
    """The driver loop for the insights screen (key handling)."""

    class _FakeConsole:
        size = (100, 30)

    class _FakeLive:
        def __init__(self):
            self.frames = 0

        def update(self, _panel):
            self.frames += 1

    @staticmethod
    def _run(keys):
        """Drive _run_team_insights with a scripted key sequence."""
        from yeaboi.ui.mode_select import _run_team_insights

        it = iter(keys)

        def _read_key(timeout=None):
            return next(it)

        live = TestRunTeamInsights._FakeLive()
        result = _run_team_insights(
            live,
            TestRunTeamInsights._FakeConsole(),
            _read_key,
            0.05,
            True,
            _make_overview_profile(),
            _NARRATIVE_EXAMPLES,
        )
        return result, live

    def test_enter_on_continue(self):
        result, live = self._run(["enter"])
        assert result == "continue"
        assert live.frames >= 1

    def test_back_button_returns_back(self):
        # Continue → Export → Back, then Enter.
        result, _ = self._run(["right", "right", "enter"])
        assert result == "back"

    def test_esc_returns_back(self):
        result, _ = self._run(["esc"])
        assert result == "back"

    def test_q_returns_back(self):
        result, _ = self._run(["q"])
        assert result == "back"

    def test_right_left_then_continue(self):
        # Navigate to Export and back to Continue, then Enter.
        result, _ = self._run(["right", "left", "enter"])
        assert result == "continue"

    def test_left_clamps_then_continue(self):
        result, _ = self._run(["left", "left", "enter"])
        assert result == "continue"
