"""Tests for analysis/engine.py — the headless team-analysis pipeline.

The engine runs three DECOUPLED components: delivery (one TeamProfile per selected
tracker), and code/docs (each ONE global scan over its own sub-sources). The result is
``{delivery:{tracker:{...}}, code:{signal,examples}|None, docs:{...}|None, comparison,
components, warnings}``.
"""

import pytest

from yeaboi.analysis import get_team_roster, run_team_analysis
from yeaboi.team_profile import AiAdoptionSignal, DocQualitySignal, TeamProfile, TeamProfileStore


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
    """Wire the engine's team_learning + code/docs primitives to fakes; returns the
    capture dict (with per-component call counts)."""
    captured: dict = {"code_calls": 0, "docs_calls": 0, "members": {}}

    def fake_jira_fetch(project, count):
        captured["fetch"] = (project, count)
        return [{"sprint_name": "Sprint 1", "stories": []}, {"sprint_name": "Sprint 2", "stories": []}]

    monkeypatch.setattr("yeaboi.tools.team_learning._fetch_jira_history", fake_jira_fetch)
    monkeypatch.setattr(
        "yeaboi.tools.team_learning._fetch_azdevops_history",
        lambda project, count: [{"sprint_name": "Iteration 1", "stories": []}],
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
        # Delivery must NOT run code/docs inline — they're global scans now.
        captured["inline_ai"] = include_ai_usage
        captured["inline_docs"] = include_doc_quality
        captured["members"][source] = members
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

    def fake_ai(source, pk, ds, alls, members=None, sub_sources=None):
        captured["code_calls"] += 1
        captured["code_sub"] = sub_sources
        captured["code_members"] = members
        return AiAdoptionSignal(scanned_commits=10, ai_commits=4, footprint_pct=40.0), {"summary": {}, "coverage": []}

    def fake_doc(source, pk, sub_sources=None):
        captured["docs_calls"] += 1
        captured["docs_sub"] = sub_sources
        return DocQualitySignal(pages_scanned=5, avg_clarity=70.0), {"summary": {}, "coverage": []}

    monkeypatch.setattr("yeaboi.analysis.ai_usage.run_ai_adoption", fake_ai)
    monkeypatch.setattr("yeaboi.analysis.doc_quality.run_doc_quality", fake_doc)
    return captured


# Full component set for the common single-tracker case.
_ALL = {"delivery": ["jira"], "code": ["github"], "docs": ["confluence"]}


class TestDelivery:
    def test_happy_path_saves_profile(self, wired, db):
        r = run_team_analysis(source="jira", project_key="PROJ", components=_ALL, db_path=db)
        assert set(r["delivery"]) == {"jira"}
        sub = r["delivery"]["jira"]
        assert sub["profile"].project_key == "PROJ"
        assert sub["insights"] is not None
        assert sub["headline_stats"]
        assert r["warnings"] == []
        # Delivery must not have run code/docs inline.
        assert wired["inline_ai"] is False and wired["inline_docs"] is False
        with TeamProfileStore(db) as store:
            assert store.list_profiles()

    def test_project_key_passthrough_single_tracker(self, wired, db):
        run_team_analysis(source="jira", project_key="ABC", components={"delivery": ["jira"]}, db_path=db)
        assert wired["fetch"] == ("ABC", 8)

    def test_sprint_count_passthrough(self, wired, db):
        run_team_analysis(
            source="jira", project_key="PROJ", sprint_count=4, components={"delivery": ["jira"]}, db_path=db
        )
        assert wired["fetch"] == ("PROJ", 4)

    def test_insights_skippable(self, wired, db, monkeypatch):
        def boom(profile, examples):
            raise AssertionError("insights must not run when include_insights=False")

        monkeypatch.setattr("yeaboi.tools.team_learning._generate_team_insights", boom)
        r = run_team_analysis(components={"delivery": ["jira"]}, include_insights=False, db_path=db)
        assert r["delivery"]["jira"]["insights"] is None

    def test_log_failure_is_warning_not_crash(self, wired, db, monkeypatch):
        def boom(*a, **kw):
            raise OSError("disk full")

        monkeypatch.setattr("yeaboi.team_profile_exporter.write_analysis_log", boom)
        r = run_team_analysis(components={"delivery": ["jira"]}, db_path=db)
        assert r["delivery"]["jira"]["log_path"] == ""
        assert any("Analysis log" in w for w in r["warnings"])

    def test_progress_list_is_shared(self, wired, db):
        progress: list[str] = []
        run_team_analysis(components={"delivery": ["jira"]}, progress=progress, db_path=db)
        assert "Analysing…" in progress

    def test_no_sprints_degrades_to_warning(self, wired, db, monkeypatch):
        monkeypatch.setattr("yeaboi.tools.team_learning._fetch_jira_history", lambda project, count: [])
        # Delivery fails, but a global code scan still returns → no raise.
        r = run_team_analysis(components={"delivery": ["jira"], "code": ["github"]}, db_path=db)
        assert r["delivery"] == {}
        assert r["code"] is not None
        assert any("delivery analysis failed" in w for w in r["warnings"])

    def test_nothing_selected_raises(self, monkeypatch, db):
        monkeypatch.setattr("yeaboi.tools.team_learning._detect_source", lambda: "")
        with pytest.raises(ValueError, match="No tracker configured"):
            run_team_analysis(components={"delivery": [], "code": [], "docs": []}, db_path=db)


class TestGlobalCodeDocs:
    def test_code_and_docs_run_once_and_attach(self, wired, db):
        r = run_team_analysis(components=_ALL, db_path=db)
        assert wired["code_calls"] == 1 and wired["docs_calls"] == 1
        assert r["code"]["signal"].footprint_pct == 40.0
        assert r["docs"]["signal"].avg_clarity == 70.0
        # Global signals attached to the saved delivery profile (stored-browser view).
        prof = r["delivery"]["jira"]["profile"]
        assert prof.ai_adoption.footprint_pct == 40.0
        assert prof.doc_quality.avg_clarity == 70.0

    def test_scanned_once_across_two_delivery_trackers(self, wired, db, monkeypatch):
        _configure(monkeypatch, jira=True, azdevops=True)
        r = run_team_analysis(
            components={"delivery": ["jira", "azdevops"], "code": ["github", "azdo"], "docs": ["confluence"]},
            db_path=db,
        )
        # The core fix: ONE code scan + ONE docs scan even with two delivery trackers.
        assert wired["code_calls"] == 1 and wired["docs_calls"] == 1
        assert wired["code_sub"] == ["github", "azdo"]
        assert wired["docs_sub"] == ["confluence"]
        # Both trackers carry the same global signal.
        assert r["delivery"]["jira"]["profile"].ai_adoption.footprint_pct == 40.0
        assert r["delivery"]["azdevops"]["profile"].ai_adoption.footprint_pct == 40.0

    def test_code_only_no_delivery(self, wired, db):
        r = run_team_analysis(components={"code": ["github"]}, db_path=db)
        assert r["delivery"] == {}
        assert r["code"] is not None and r["docs"] is None
        # No delivery profile → nothing persisted.
        with TeamProfileStore(db) as store:
            assert store.list_profiles() == []

    def test_docs_only_no_delivery(self, wired, db):
        r = run_team_analysis(components={"docs": ["confluence"]}, db_path=db)
        assert r["delivery"] == {} and r["code"] is None
        assert r["docs"]["signal"].avg_clarity == 70.0


def _configure(monkeypatch, *, jira=True, azdevops=True):
    """Toggle which trackers _available_sources() sees as configured."""
    monkeypatch.setattr("yeaboi.config.get_jira_base_url", lambda: "https://x.atlassian.net" if jira else None)
    monkeypatch.setattr("yeaboi.config.get_jira_token", lambda: "tok" if jira else None)
    monkeypatch.setattr(
        "yeaboi.config.get_azure_devops_org_url", lambda: "https://dev.azure.com/x" if azdevops else None
    )
    monkeypatch.setattr("yeaboi.config.get_azure_devops_token", lambda: "pat" if azdevops else None)


class TestMultiTrackerDelivery:
    def test_both_trackers_separate_profiles(self, wired, db, monkeypatch):
        _configure(monkeypatch, jira=True, azdevops=True)
        r = run_team_analysis(components={"delivery": ["jira", "azdevops"]}, db_path=db)
        assert set(r["delivery"]) == {"jira", "azdevops"}
        assert r["delivery"]["jira"]["profile"].source == "jira"
        assert r["delivery"]["azdevops"]["profile"].source == "azdevops"
        assert r["comparison"]  # side-by-side rows when >=2 delivery trackers
        assert "Avg velocity" in [row[0] for row in r["comparison"]]
        with TeamProfileStore(db) as store:
            assert len(store.list_profiles()) == 2

    def test_source_both_default_components(self, wired, db, monkeypatch):
        _configure(monkeypatch, jira=True, azdevops=True)
        r = run_team_analysis(source="both", db_path=db)
        assert set(r["delivery"]) == {"jira", "azdevops"}

    def test_one_tracker_fails_other_returns(self, wired, db, monkeypatch):
        _configure(monkeypatch, jira=True, azdevops=True)
        monkeypatch.setattr("yeaboi.tools.team_learning._fetch_azdevops_history", lambda project, count: [])
        r = run_team_analysis(components={"delivery": ["jira", "azdevops"]}, db_path=db)
        assert set(r["delivery"]) == {"jira"}
        assert any("Azure DevOps delivery analysis failed" in w for w in r["warnings"])
        assert r["comparison"] == []  # only one tracker survived


class TestMemberSubset:
    def test_members_reach_delivery_and_code(self, wired, db):
        run_team_analysis(components=_ALL, members={"jira": ["Alice"]}, db_path=db)
        assert wired["members"]["jira"] == ["Alice"]
        # Code author filter uses the union of selected members.
        assert wired["code_members"] == ["Alice"]

    def test_members_union_across_trackers_for_code(self, wired, db, monkeypatch):
        _configure(monkeypatch, jira=True, azdevops=True)
        run_team_analysis(
            components={"delivery": ["jira", "azdevops"], "code": ["github"]},
            members={"jira": ["Alice"], "azdevops": ["Bob"]},
            db_path=db,
        )
        assert wired["members"]["jira"] == ["Alice"]
        assert wired["members"]["azdevops"] == ["Bob"]
        assert wired["code_members"] == ["Alice", "Bob"]  # sorted union


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
        monkeypatch.setattr("yeaboi.tools.team_learning._fetch_jira_history", lambda project, count: [])
        assert get_team_roster(source="jira", project_key="PROJ") == []

    def test_no_tracker_raises(self, monkeypatch):
        monkeypatch.setattr("yeaboi.tools.team_learning._detect_source", lambda: "")
        with pytest.raises(ValueError, match="No tracker configured"):
            get_team_roster()


class TestCliRunLearn:
    def test_learn_uses_engine_and_real_db(self, monkeypatch):
        import io

        from rich.console import Console

        from yeaboi.cli import _run_learn

        called: dict = {}

        def fake_run(**kwargs):
            called.update(kwargs)
            return {
                "delivery": {"jira": {"profile": _profile()}},
                "code": None,
                "docs": None,
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
