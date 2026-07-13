"""Unit tests for reporting/export — Markdown, HTML, and file writing."""

from scrum_agent.agent.state import DeliveredItem, DeliveryReport
from scrum_agent.reporting import export


def _report():
    return DeliveryReport(
        period_label="Last sprint",
        period_start="2026-06-29",
        period_end="2026-07-13",
        project_name="Acme Portal",
        sprint_names=("Sprint 12",),
        headline="Shipped SSO.",
        executive_summary="We delivered single sign-on.",
        themes=(("Security", ("SSO login", "MFA rollout")),),
        highlights=("SSO live for all users",),
        metrics=(("Items delivered", "7"), ("Contributors", "3")),
        delivered_items=(
            DeliveredItem(
                key="ACME-1", title="SSO <script>alert(1)</script>", status="Done", source="jira", assignee="Ada"
            ),
        ),
        emoji_theme=(("headline", "🚀"), ("metrics", "📊")),
        warnings=("test warning",),
        generated_at="2026-07-13",
    )


class TestMarkdown:
    def test_contains_sections(self):
        md = export.build_report_markdown(_report())
        assert "# 🚀 Delivery Report — Acme Portal" in md
        assert "Last sprint" in md
        assert "By the numbers" in md
        assert "Security" in md
        assert "ACME-1" in md
        assert "test warning" in md

    def test_empty_report_renders(self):
        md = export.build_report_markdown(DeliveryReport(period_label="Last month (~2 sprints)"))
        assert "Delivery Report" in md


class TestHtml:
    def test_self_contained_and_escaped(self):
        html = export.build_report_html(_report())
        assert html.lstrip().startswith("<!DOCTYPE html>")
        assert "<style>" in html  # inline CSS, no external stylesheet
        # Untrusted ticket title must be escaped, never live markup.
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html
        assert "ACME-1" in html

    def test_metrics_cards_present(self):
        html = export.build_report_html(_report())
        assert "By the numbers" in html
        assert "Items delivered" in html


class TestExportReport:
    def test_writes_three_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("scrum_agent.paths.get_reporting_export_dir", lambda key: tmp_path)
        paths = export.export_report(_report(), theme="aurora")
        assert set(paths) == {"markdown", "html", "slides"}
        for p in paths.values():
            assert p.exists() and p.read_text(encoding="utf-8")
        assert paths["slides"].name.endswith("-slides.html")
