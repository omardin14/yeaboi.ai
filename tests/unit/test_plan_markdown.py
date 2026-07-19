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

    def test_attachments_section_from_pasted_images(self, tmp_path):
        img1 = tmp_path / "one.png"
        img2 = tmp_path / "two.png"
        img1.write_bytes(b"1")
        img2.write_bytes(b"2")
        state = {
            "pasted_images": [str(img1)],
            "chat_images": [str(img2), str(img1)],  # duplicate deduped
        }
        md = build_plan_markdown(state)
        assert "# Attachments" in md
        assert f"![Screenshot 1]({img1})" in md
        assert f"![Screenshot 2]({img2})" in md
        assert md.count(str(img1)) == 1

    def test_missing_attachment_files_omitted(self, tmp_path):
        md = build_plan_markdown({"pasted_images": [str(tmp_path / "gone.png")]})
        assert "# Attachments" not in md

    def test_export_localizes_attachments(self, tmp_path):
        img = tmp_path / "shot.png"
        img.write_bytes(b"png")
        out_dir = tmp_path / "export"
        out_dir.mkdir()
        out = _export_plan_markdown({"pasted_images": [str(img)]}, path=out_dir / "plan.md")
        assert "![Screenshot 1](images/shot.png)" in out.read_text()
        assert (out_dir / "images" / "shot.png").exists()
