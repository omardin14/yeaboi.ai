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

    def fake_parallel(source, project, sprint_data, progress):
        progress.append("Analysing…")
        captured["parallel"] = (source, project, len(sprint_data))
        return _profile(source=source, project_key=project), {"sprint_details": []}

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
