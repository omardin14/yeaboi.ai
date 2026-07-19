"""Tests for repl/_io.py's plan Markdown builder (extracted for Notion/Confluence export)."""

from __future__ import annotations

from yeaboi.repl._io import _export_plan_markdown, build_plan_markdown


class TestBuildPlanMarkdown:
    def test_empty_state_returns_string(self):
        md = build_plan_markdown({})
        assert isinstance(md, str)

    def test_includes_analysis_heading(self):
        from tests._node_helpers import make_dummy_analysis

        md = build_plan_markdown({"project_analysis": make_dummy_analysis()})
        analysis = make_dummy_analysis()
        assert f"# {analysis.project_name}" in md
        assert "**Description:**" in md

    def test_export_writes_builder_output(self, tmp_path):
        from tests._node_helpers import make_dummy_analysis

        state = {"project_analysis": make_dummy_analysis()}
        out = _export_plan_markdown(state, path=tmp_path / "plan.md")
        assert out == tmp_path / "plan.md"
        assert out.read_text() == build_plan_markdown(state)
