"""Unit tests for reporting/presentation — the self-contained slide deck."""

import json

from yeaboi.agent.state import DeliveredItem, DeliveryReport
from yeaboi.reporting import presentation


def _report():
    return DeliveryReport(
        period_label="Last month (~2 sprints)",
        period_start="2026-06-15",
        period_end="2026-07-13",
        project_name="Acme Portal",
        sprint_names=("Sprint 11", "Sprint 12"),
        headline="Two sprints of strong delivery.",
        executive_summary="We shipped SSO and cut checkout time.",
        themes=(("Security", ("SSO", "MFA")), ("Performance", ("Faster checkout",))),
        highlights=("SSO live", "2x faster checkout"),
        metrics=(("Items delivered", "12"),),
        delivered_items=(DeliveredItem(key="A-1", title="x", status="Done"),),
        emoji_theme=(("headline", "🚀"), ("themes", "🧩"), ("highlights", "⭐")),
    )


class TestBuildSlides:
    def test_slide_order_and_types(self):
        slides = presentation._build_slides(_report())
        types = [s["type"] for s in slides]
        assert types[0] == "title"
        assert types[-1] == "thanks"
        assert "summary" in types
        assert "metrics" in types
        assert types.count("list") == 3  # 2 themes + highlights

    def test_empty_report_still_has_title_and_thanks(self):
        slides = presentation._build_slides(DeliveryReport(period_label="Last sprint"))
        types = [s["type"] for s in slides]
        assert types == ["title", "thanks"]


class TestBuildPresentationHtml:
    def test_self_contained(self):
        html = presentation.build_presentation_html(_report(), theme="aurora")
        assert html.lstrip().startswith("<!DOCTYPE html>")
        assert 'data-theme="aurora"' in html
        assert "<style>" in html and "<script>" in html
        # No external resources (offline).
        assert "http://" not in html and "https://" not in html
        assert "cdn" not in html.lower()

    def test_untrusted_text_is_json_encoded_not_raw_markup(self):
        r = DeliveryReport(
            period_label="Last sprint",
            headline="hi",
            themes=(("T", ("<img src=x onerror=alert(1)>",)),),
            emoji_theme=(("themes", "🧩"),),
        )
        html = presentation.build_presentation_html(r)
        # The payload lives inside the JSON slide array, angle brackets escaped by json.dumps
        # (<), so it can never appear as a live tag in the document.
        assert "<img src=x onerror=alert(1)>" not in html
        assert "\\u003cimg" in html or "onerror" in html  # present, but encoded

    def test_invalid_theme_falls_back_to_midnight(self):
        html = presentation.build_presentation_html(_report(), theme="nonsense")
        assert 'data-theme="midnight"' in html

    def test_slides_json_parses(self):
        html = presentation.build_presentation_html(_report())
        # Extract the injected SLIDES array and confirm it is valid JSON.
        marker = "const SLIDES = "
        start = html.index(marker) + len(marker)
        end = html.index(";\n", start)
        data = json.loads(html[start:end])
        assert isinstance(data, list) and data[0]["type"] == "title"
