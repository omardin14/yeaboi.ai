"""Tests for analysis/engine.py — the headless team-analysis pipeline."""

import pytest

from yeaboi.analysis import run_team_analysis
from yeaboi.team_profile import TeamProfile, TeamProfileStore


def _profile(**overrides) -> TeamProfile:
    defaults = dict(
        team_id="jira:PROJ",
        source="jira",
        project_key="PROJ",
        sample_sprints=8,
        sample_stories=40,
        velocity_avg=32.0,
        velocity_stddev=4.0,
    )
    defaults.update(overrides)
    return TeamProfile(**defaults)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "sessions.db"


@pytest.fixture
def wired(monkeypatch, db, tmp_path):
    """Wire the engine's team_learning primitives to fakes; returns the capture dict."""
    captured: dict = {}

    def fake_jira_fetch(project, count):
        captured["fetch"] = (project, count)
        return [{"sprint_name": "Sprint 1"}, {"sprint_name": "Sprint 2"}]

    monkeypatch.setattr("yeaboi.tools.team_learning._fetch_jira_history", fake_jira_fetch)
    monkeypatch.setattr(
        "yeaboi.tools.team_learning._fetch_azdevops_history",
        lambda project, count: [{"sprint_name": "Iteration 1"}],
    )

    def fake_parallel(
        source,
        project,
        sprint_data,
        progress,
        include_ai_usage=True,
        include_doc_quality=True,
        members=None,
        warnings=None,
    ):
        progress.append("Analysing…")
        captured["parallel"] = (source, project, len(sprint_data))
        captured["include_ai_usage"] = include_ai_usage
        captured["include_doc_quality"] = include_doc_quality
        captured["members"] = members
        # Distinct team_id per source (the DB primary key), mirroring the real
        # analysis so a 'both' run persists two rows rather than colliding.
        return _profile(team_id=f"{source}:{project}", source=source, project_key=project), {"sprint_details": []}

    monkeypatch.setattr("yeaboi.tools.team_learning._run_parallel_analysis", fake_parallel)
    monkeypatch.setattr(
        "yeaboi.team_profile_exporter.write_analysis_log",
        lambda profile, *, examples, sprint_names, duration_secs: tmp_path / "analysis.log",
    )
    monkeypatch.setattr(
        "yeaboi.tools.team_learning._generate_team_insights",
        lambda profile, examples: {"start": [], "stop": [], "keep": [], "try": []},
    )
    return captured


class TestRunTeamAnalysis:
    def test_happy_path_saves_profile(self, wired, db):
        result = run_team_analysis(source="jira", project_key="PROJ", db_path=db)
        assert result["source"] == "jira"
        assert result["sprint_names"] == ["Sprint 1", "Sprint 2"]
        assert result["profile"].project_key == "PROJ"
        assert result["insights"] is not None
        assert result["headline_stats"]
        assert result["warnings"] == []
        with TeamProfileStore(db) as store:
            assert store.list_profiles()

    def test_sprint_count_passthrough(self, wired, db):
        run_team_analysis(source="jira", project_key="PROJ", sprint_count=4, db_path=db)
        assert wired["fetch"] == ("PROJ", 4)

    def test_no_tracker_raises(self, monkeypatch, db):
        monkeypatch.setattr("yeaboi.tools.team_learning._detect_source", lambda: "")
        with pytest.raises(ValueError, match="No tracker configured"):
            run_team_analysis(db_path=db)

    def test_no_sprints_raises(self, monkeypatch, db):
        monkeypatch.setattr("yeaboi.tools.team_learning._fetch_jira_history", lambda project, count: [])
        with pytest.raises(ValueError, match="No closed sprints"):
            run_team_analysis(source="jira", project_key="PROJ", db_path=db)

    def test_insights_skippable(self, wired, db, monkeypatch):
        def boom(profile, examples):
            raise AssertionError("insights must not run when include_insights=False")

        monkeypatch.setattr("yeaboi.tools.team_learning._generate_team_insights", boom)
        result = run_team_analysis(source="jira", project_key="PROJ", include_insights=False, db_path=db)
        assert result["insights"] is None

    def test_azdo_team_name_attached(self, wired, db):
        result = run_team_analysis(source="azdevops", project_key="Web", team_name="Falcons", db_path=db)
        assert result["profile"].team_name == "Falcons"

    def test_log_failure_is_warning_not_crash(self, wired, db, monkeypatch):
        def boom(*a, **kw):
            raise OSError("disk full")

        monkeypatch.setattr("yeaboi.team_profile_exporter.write_analysis_log", boom)
        result = run_team_analysis(source="jira", project_key="PROJ", db_path=db)
        assert result["log_path"] == ""
        assert any("Analysis log" in w for w in result["warnings"])

    def test_progress_list_is_shared(self, wired, db):
        progress: list[str] = []
        run_team_analysis(source="jira", project_key="PROJ", progress=progress, db_path=db)
        assert "Analysing…" in progress

    def test_samples_generated_on_request(self, wired, db, monkeypatch):
        monkeypatch.setattr("yeaboi.agent.nodes._format_team_calibration", lambda p, *, examples=None: "calib")
        monkeypatch.setattr("yeaboi.tools.team_learning.generate_sample_epic", lambda c, ex: {"title": "Epic"})
        monkeypatch.setattr("yeaboi.tools.team_learning.generate_sample_stories", lambda c, e, ex: [{"title": "S1"}])
        monkeypatch.setattr("yeaboi.tools.team_learning.generate_sample_tasks", lambda c, s, ex: [{"title": "T1"}])
        monkeypatch.setattr("yeaboi.tools.team_learning.generate_sample_sprint", lambda c, s, t, ex: {"name": "Sp"})
        result = run_team_analysis(source="jira", project_key="PROJ", generate_samples=True, db_path=db)
        assert result["samples"]["epic"] == {"title": "Epic"}
        assert result["samples"]["stories"] == [{"title": "S1"}]

    def test_sample_failure_is_warning(self, wired, db, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("llm down")

        monkeypatch.setattr("yeaboi.agent.nodes._format_team_calibration", boom)
        result = run_team_analysis(source="jira", project_key="PROJ", generate_samples=True, db_path=db)
        assert result["samples"] is None
        assert any("Sample-ticket" in w for w in result["warnings"])


def _configure(monkeypatch, *, jira=True, azdevops=True):
    """Toggle which trackers _available_sources() sees as configured."""
    monkeypatch.setattr("yeaboi.config.get_jira_base_url", lambda: "https://x.atlassian.net" if jira else None)
    monkeypatch.setattr("yeaboi.config.get_jira_token", lambda: "tok" if jira else None)
    monkeypatch.setattr(
        "yeaboi.config.get_azure_devops_org_url", lambda: "https://dev.azure.com/x" if azdevops else None
    )
    monkeypatch.setattr("yeaboi.config.get_azure_devops_token", lambda: "pat" if azdevops else None)


class TestRunTeamAnalysisBoth:
    def test_both_runs_each_tracker_separately(self, wired, db, monkeypatch):
        _configure(monkeypatch, jira=True, azdevops=True)
        result = run_team_analysis(source="both", db_path=db)
        assert result["source"] == "both"
        assert set(result["results"]) == {"jira", "azdevops"}
        # Each keeps its own source-stamped profile — never blended.
        assert result["results"]["jira"]["profile"].source == "jira"
        assert result["results"]["azdevops"]["profile"].source == "azdevops"
        assert result["comparison"]  # side-by-side headline rows
        labels = [row[0] for row in result["comparison"]]
        assert "Avg velocity" in labels
        # Both profiles persisted as separate rows.
        with TeamProfileStore(db) as store:
            assert len(store.list_profiles()) == 2

    def test_both_only_one_configured_degrades_to_single(self, wired, db, monkeypatch):
        _configure(monkeypatch, jira=True, azdevops=False)
        result = run_team_analysis(source="both", db_path=db)
        # Degrades to a normal single-source result the surfaces render as-is.
        assert result["source"] == "jira"
        assert "results" not in result
        assert any("Only Jira" in w for w in result["warnings"])

    def test_both_neither_configured_raises(self, wired, db, monkeypatch):
        _configure(monkeypatch, jira=False, azdevops=False)
        monkeypatch.setattr("yeaboi.tools.team_learning._detect_source", lambda: "")
        with pytest.raises(ValueError, match="No tracker configured"):
            run_team_analysis(source="both", db_path=db)

    def test_both_one_source_fails_degrades_with_warning(self, wired, db, monkeypatch):
        _configure(monkeypatch, jira=True, azdevops=True)
        # Azure DevOps has no closed sprints → that single run raises; Jira still returns.
        monkeypatch.setattr("yeaboi.tools.team_learning._fetch_azdevops_history", lambda project, count: [])
        result = run_team_analysis(source="both", db_path=db)
        assert result["source"] == "both"
        assert set(result["results"]) == {"jira"}
        assert any("Azure DevOps analysis failed" in w for w in result["warnings"])

    def test_both_all_fail_raises(self, wired, db, monkeypatch):
        _configure(monkeypatch, jira=True, azdevops=True)
        monkeypatch.setattr("yeaboi.tools.team_learning._fetch_jira_history", lambda project, count: [])
        monkeypatch.setattr("yeaboi.tools.team_learning._fetch_azdevops_history", lambda project, count: [])
        with pytest.raises(ValueError, match="Both trackers failed"):
            run_team_analysis(source="both", db_path=db)


class TestComponentSelection:
    def test_legacy_ai_usage_flag_folds_into_components(self, wired, db):
        run_team_analysis(source="jira", project_key="PROJ", include_ai_usage=False, db_path=db)
        assert wired["include_ai_usage"] is False
        assert wired["include_doc_quality"] is True

    def test_delivery_only_components_skip_code_and_docs(self, wired, db):
        run_team_analysis(source="jira", project_key="PROJ", components={"jira": ["delivery"]}, db_path=db)
        assert wired["include_ai_usage"] is False
        assert wired["include_doc_quality"] is False

    def test_components_none_reproduces_default(self, wired, db):
        run_team_analysis(source="jira", project_key="PROJ", components=None, db_path=db)
        assert wired["include_ai_usage"] is True
        assert wired["include_doc_quality"] is True

    def test_delivery_off_docs_only(self, wired, db, monkeypatch):
        # Delivery off → no board fetch, no profile, not persisted.
        def boom_fetch(project, count):
            raise AssertionError("board must not be fetched when delivery is off")

        monkeypatch.setattr("yeaboi.tools.team_learning._fetch_jira_history", boom_fetch)
        monkeypatch.setattr(
            "yeaboi.tools.team_learning.run_components_only",
            lambda source, project, run_code, run_docs, members, progress: {
                "doc_quality": {"summary": {"pages_scanned": 3}},
                "_signals": {},
            },
        )
        result = run_team_analysis(source="jira", project_key="PROJ", components={"jira": ["docs"]}, db_path=db)
        assert result["profile"] is None
        assert result["components"] == ["docs"]
        assert result["headline_stats"] is None
        assert result["insights"] is None
        assert result["samples"] is None
        assert "doc_quality" in result["examples"]
        # Nothing persisted for a delivery-off run.
        with TeamProfileStore(db) as store:
            assert store.list_profiles() == []

    def test_delivery_off_does_not_raise_on_empty_board(self, wired, db, monkeypatch):
        monkeypatch.setattr("yeaboi.tools.team_learning._fetch_jira_history", lambda project, count: [])
        monkeypatch.setattr(
            "yeaboi.tools.team_learning.run_components_only",
            lambda *a, **k: {"ai_adoption": {"summary": {}}, "_signals": {}},
        )
        result = run_team_analysis(source="jira", project_key="PROJ", components={"jira": ["code"]}, db_path=db)
        assert result["profile"] is None
        assert result["components"] == ["code"]

    def test_both_per_source_components(self, wired, db, monkeypatch):
        _configure(monkeypatch, jira=True, azdevops=True)
        monkeypatch.setattr(
            "yeaboi.tools.team_learning.run_components_only",
            lambda *a, **k: {"doc_quality": {"summary": {}}, "_signals": {}},
        )
        result = run_team_analysis(
            source="both",
            components={"jira": ["delivery"], "azdevops": ["docs"]},
            db_path=db,
        )
        assert result["results"]["jira"]["profile"] is not None
        assert result["results"]["azdevops"]["profile"] is None
        assert result["results"]["azdevops"]["components"] == ["docs"]


class TestMemberSubset:
    def test_members_passed_through_to_analysis(self, wired, db):
        run_team_analysis(source="jira", project_key="PROJ", members={"jira": ["Alice", "Bob"]}, db_path=db)
        assert wired["members"] == ["Alice", "Bob"]

    def test_members_none_by_default(self, wired, db):
        run_team_analysis(source="jira", project_key="PROJ", db_path=db)
        assert wired["members"] is None

    def test_both_per_source_members(self, wired, db, monkeypatch):
        _configure(monkeypatch, jira=True, azdevops=True)
        seen: list = []

        def fake_parallel(source, project, sprint_data, progress, members=None, **kw):
            seen.append((source, members))
            return _profile(team_id=f"{source}:{project}", source=source, project_key=project), {}

        monkeypatch.setattr("yeaboi.tools.team_learning._run_parallel_analysis", fake_parallel)
        run_team_analysis(
            source="both",
            members={"jira": ["Alice"], "azdevops": ["Zoe"]},
            db_path=db,
        )
        assert ("jira", ["Alice"]) in seen
        assert ("azdevops", ["Zoe"]) in seen


class TestSelectedMemberVelocity:
    def test_sums_selected_per_sprint_case_insensitive(self):
        from yeaboi.tools.team_learning import selected_member_velocity

        contrib = [
            {"name": "Alice", "per_sprint": 8.0},
            {"name": "Bob", "per_sprint": 5.0},
            {"name": "Carol", "per_sprint": 3.0},
        ]
        assert selected_member_velocity(contrib, ["alice", "bob"]) == 13.0

    def test_empty_inputs(self):
        from yeaboi.tools.team_learning import selected_member_velocity

        assert selected_member_velocity([], ["Alice"]) == 0.0
        assert selected_member_velocity([{"name": "A", "per_sprint": 5}], []) == 0.0


class TestGetTeamRoster:
    def test_returns_sorted_unique_assignees(self, monkeypatch):
        from yeaboi.analysis import get_team_roster

        monkeypatch.setattr(
            "yeaboi.tools.team_learning._fetch_jira_history",
            lambda project, count: [
                {"sprint_name": "S1", "stories": [{"assignee": "Bob"}, {"assignee": "Alice"}]},
                {"sprint_name": "S2", "stories": [{"assignee": "Alice"}, {"assignee": ""}]},
            ],
        )

        def boom(*a, **k):
            raise AssertionError("roster must not run the LLM analysis")

        monkeypatch.setattr("yeaboi.tools.team_learning._run_parallel_analysis", boom)
        assert get_team_roster(source="jira", project_key="PROJ") == ["Alice", "Bob"]

    def test_empty_board_returns_empty(self, monkeypatch):
        from yeaboi.analysis import get_team_roster

        monkeypatch.setattr("yeaboi.tools.team_learning._fetch_jira_history", lambda project, count: [])
        assert get_team_roster(source="jira", project_key="PROJ") == []

    def test_no_tracker_raises(self, monkeypatch):
        from yeaboi.analysis import get_team_roster

        monkeypatch.setattr("yeaboi.tools.team_learning._detect_source", lambda: "")
        with pytest.raises(ValueError, match="No tracker configured"):
            get_team_roster()


class TestCliRunLearn:
    def test_learn_uses_engine_and_real_db(self, wired, db, monkeypatch, capsys):
        # Regression: _run_learn used to write to ~/.scrum-agent/sessions.db
        # via the lossier analyze_team_history path.
        import io

        from rich.console import Console

        from yeaboi.cli import _run_learn

        called: dict = {}

        def fake_run(**kwargs):
            called.update(kwargs)
            return {
                "profile": _profile(),
                "warnings": ["Jira rate limited"],
            }

        monkeypatch.setattr("yeaboi.analysis.engine.run_team_analysis", fake_run)
        monkeypatch.setattr("yeaboi.analysis.run_team_analysis", fake_run)
        buf = io.StringIO()
        _run_learn(Console(file=buf, width=100))
        out = buf.getvalue()
        assert "Team profile saved for jira/PROJ" in out
        assert "Jira rate limited" in out
        assert called == {"include_insights": False}  # engine defaults handle DB + source

    def test_learn_prints_engine_error(self, monkeypatch):
        import io

        from rich.console import Console

        from yeaboi.cli import _run_learn

        def boom(**kwargs):
            raise ValueError("No tracker configured for analysis")

        monkeypatch.setattr("yeaboi.analysis.run_team_analysis", boom)
        buf = io.StringIO()
        _run_learn(Console(file=buf, width=100))
        assert "No tracker configured" in buf.getvalue()
