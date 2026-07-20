"""Unit tests for the Roadmap engine pipeline (mocked LLM + ingestion)."""

import json

import pytest

from yeaboi.roadmap import engine
from yeaboi.roadmap.ingest import RoadmapSource


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "sessions.db"


class _FakeResp:
    def __init__(self, content):
        self.content = content
        self.response_metadata = {}


def _patch_llm(monkeypatch, content):
    """Make the engine's single LLM call return ``content`` and report configured."""
    monkeypatch.setattr("yeaboi.config.is_llm_configured", lambda: (True, ""))
    monkeypatch.setattr("yeaboi.agent.llm.track_usage", lambda resp: None)
    monkeypatch.setattr(
        "yeaboi.agent.llm.get_llm",
        lambda **k: type("L", (), {"invoke": lambda self, m: _FakeResp(content)})(),
    )


def _patch_ingest(monkeypatch, text="Q3: SSO and checkout.", label="Q3 Roadmap", warnings=()):
    monkeypatch.setattr(engine, "ingest_source", lambda source: (text, label, list(warnings)))


def _source():
    return RoadmapSource(source_type="confluence", locator="42", label="Q3 Roadmap")


def _llm_json(projects=None, summary="Two initiatives."):
    if projects is None:
        projects = [
            {
                "name": "Checkout revamp",
                "description": "Rebuild the checkout flow.",
                "size": "large",
                "rationale": "Multi-sprint.",
                "priority": 2,
                "themes": ["Revenue"],
                "quarter": "Q3 2026",
            },
            {
                "name": "SSO",
                "description": "Add single sign-on.",
                "size": "large",
                "rationale": "Start first.",
                "priority": 1,
                "themes": ["Security"],
                "quarter": "Q3 2026",
            },
        ]
    return json.dumps({"summary": summary, "projects": projects})


class TestRunRoadmapAnalysis:
    def test_happy_path_parses_and_sorts_by_priority(self, monkeypatch, db_path):
        _patch_ingest(monkeypatch)
        _patch_llm(monkeypatch, _llm_json())
        analysis = engine.run_roadmap_analysis(_source(), db_path=db_path)
        assert analysis.summary == "Two initiatives."
        assert [p.name for p in analysis.projects] == ["SSO", "Checkout revamp"]  # priority-sorted
        assert analysis.projects[0].themes == ("Security",)
        assert analysis.source_label == "Q3 Roadmap"
        assert not analysis.warnings

    def test_code_fenced_json_parses(self, monkeypatch, db_path):
        _patch_ingest(monkeypatch)
        _patch_llm(monkeypatch, f"```json\n{_llm_json()}\n```")
        analysis = engine.run_roadmap_analysis(_source(), db_path=db_path)
        assert len(analysis.projects) == 2

    def test_malformed_json_falls_back(self, monkeypatch, db_path):
        _patch_ingest(monkeypatch)
        _patch_llm(monkeypatch, "not json at all")
        analysis = engine.run_roadmap_analysis(_source(), db_path=db_path)
        assert analysis.projects == ()
        assert any("could not find concrete projects" in w for w in analysis.warnings)

    def test_size_coercion_and_bad_entries_skipped(self, monkeypatch, db_path):
        projects = [
            {"name": "A", "size": "MEGA", "priority": "not-a-number"},
            "garbage",
            {"description": "nameless — skipped"},
            {"name": "B", "size": "Large", "priority": 1},
        ]
        _patch_ingest(monkeypatch)
        _patch_llm(monkeypatch, _llm_json(projects=projects))
        analysis = engine.run_roadmap_analysis(_source(), db_path=db_path)
        assert [p.name for p in analysis.projects] == ["B", "A"]  # ranked first, unranked last
        assert analysis.projects[1].size == "small"  # unknown size coerced
        assert analysis.projects[0].size == "large"  # case-normalized

    def test_unconfigured_llm_falls_back_with_warning(self, monkeypatch, db_path):
        _patch_ingest(monkeypatch)
        monkeypatch.setattr("yeaboi.config.is_llm_configured", lambda: (False, "no API key set"))
        analysis = engine.run_roadmap_analysis(_source(), db_path=db_path)
        assert analysis.projects == ()
        assert any("no API key set" in w for w in analysis.warnings)

    def test_auth_error_becomes_warning_not_raise(self, monkeypatch, db_path):
        _patch_ingest(monkeypatch)
        monkeypatch.setattr("yeaboi.config.is_llm_configured", lambda: (True, ""))
        # The detector matches provider exception classes; force the auth branch.
        monkeypatch.setattr("yeaboi.agent.nodes._is_llm_auth_or_billing_error", lambda exc: True)

        def _boom(**k):
            raise RuntimeError("invalid x-api-key")

        monkeypatch.setattr("yeaboi.agent.llm.get_llm", _boom)
        analysis = engine.run_roadmap_analysis(_source(), db_path=db_path)
        assert analysis.projects == ()
        assert any("API key invalid or billing issue" in w for w in analysis.warnings)

    def test_generic_llm_error_becomes_warning(self, monkeypatch, db_path):
        _patch_ingest(monkeypatch)
        monkeypatch.setattr("yeaboi.config.is_llm_configured", lambda: (True, ""))

        def _boom(**k):
            raise RuntimeError("network down")

        monkeypatch.setattr("yeaboi.agent.llm.get_llm", _boom)
        analysis = engine.run_roadmap_analysis(_source(), db_path=db_path)
        assert analysis.projects == ()
        assert any("LLM request failed" in w for w in analysis.warnings)

    def test_empty_ingest_skips_llm(self, monkeypatch, db_path):
        _patch_ingest(monkeypatch, text="", warnings=["Roadmap file not found: /x.md"])

        def _fail(**k):  # the LLM must never be constructed
            raise AssertionError("LLM should not be called when ingest is empty")

        monkeypatch.setattr("yeaboi.agent.llm.get_llm", _fail)
        analysis = engine.run_roadmap_analysis(_source(), db_path=db_path)
        assert analysis.projects == ()
        assert any("not found" in w for w in analysis.warnings)

    def test_ingest_warnings_carried_into_analysis(self, monkeypatch, db_path):
        _patch_ingest(monkeypatch, warnings=["Roadmap truncated at 24,000 characters"])
        _patch_llm(monkeypatch, _llm_json())
        analysis = engine.run_roadmap_analysis(_source(), db_path=db_path)
        assert len(analysis.projects) == 2
        assert any("truncated" in w for w in analysis.warnings)

    def test_dry_run_is_canned_and_offline(self, monkeypatch, db_path):
        def _fail(**k):
            raise AssertionError("no LLM in dry-run")

        monkeypatch.setattr("yeaboi.agent.llm.get_llm", _fail)
        monkeypatch.setattr(engine, "ingest_source", _fail)
        analysis = engine.run_roadmap_analysis(_source(), db_path=db_path, dry_run=True)
        assert len(analysis.projects) == 3
        assert {p.size for p in analysis.projects} == {"small", "large"}

    def test_record_run_persists(self, monkeypatch, db_path):
        from yeaboi.roadmap.store import RoadmapStore

        _patch_ingest(monkeypatch)
        _patch_llm(monkeypatch, _llm_json())
        engine.run_roadmap_analysis(_source(), db_path=db_path)
        with RoadmapStore(db_path) as store:
            latest = store.get_latest_analysis()
            assert latest is not None and len(latest.projects) == 2

    def test_store_failure_never_raises(self, monkeypatch, tmp_path):
        _patch_ingest(monkeypatch)
        _patch_llm(monkeypatch, _llm_json())
        analysis = engine.run_roadmap_analysis(_source(), db_path=tmp_path / "no" / "such" / "dir" / "x.db")
        assert len(analysis.projects) == 2  # analysis still returned

    def test_on_progress_reports_pipeline_stages(self, monkeypatch, db_path):
        _patch_ingest(monkeypatch)
        _patch_llm(monkeypatch, _llm_json())
        steps: list[str] = []
        engine.run_roadmap_analysis(_source(), db_path=db_path, on_progress=steps.append)
        assert any("roadmap source" in s for s in steps)  # ingest stage
        assert any("Analyzing" in s for s in steps)  # LLM stage
        assert steps == [s for s in steps]  # all strings, in order

    def test_on_progress_callback_error_is_swallowed(self, monkeypatch, db_path):
        _patch_ingest(monkeypatch)
        _patch_llm(monkeypatch, _llm_json())

        def _boom(msg):
            raise RuntimeError("progress UI bug")

        analysis = engine.run_roadmap_analysis(_source(), db_path=db_path, on_progress=_boom)
        assert len(analysis.projects) == 2  # pipeline unaffected


class TestIntakeModeFor:
    def test_mapping(self):
        from yeaboi.agent.state import RoadmapProject
        from yeaboi.roadmap.engine import intake_mode_for

        assert intake_mode_for(RoadmapProject(size="small")) == "small_project"
        assert intake_mode_for(RoadmapProject(size="large")) == "smart"
        assert intake_mode_for(RoadmapProject(size="weird")) == "small_project"


class TestRenderLines:
    def test_format_analysis_lines(self):
        from yeaboi.agent.state import RoadmapAnalysis, RoadmapProject
        from yeaboi.roadmap.render import format_analysis_lines

        analysis = RoadmapAnalysis(
            summary="Overview.",
            projects=(
                RoadmapProject(name="SSO", size="large", rationale="Epic.", priority=1, quarter="Q3 2026"),
                RoadmapProject(name="Emails", size="small", priority=2),
            ),
            warnings=("something happened",),
        )
        lines = format_analysis_lines(analysis, selected_idx=0)
        text = "\n".join(lines)
        assert "Overview." in text
        assert "▸ 1. SSO  [Large]" in text
        assert "  2. Emails  [Small]" in text
        assert "⚠ Notices:" in text
        assert "something happened" in text

    def test_empty_analysis_renders(self):
        from yeaboi.agent.state import RoadmapAnalysis
        from yeaboi.roadmap.render import format_analysis_lines

        lines = format_analysis_lines(RoadmapAnalysis())
        assert any("No projects extracted" in ln for ln in lines)
