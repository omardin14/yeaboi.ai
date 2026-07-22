"""Tests for the documentation-quality sub-analysis (analysis/doc_quality.py) and its wiring.

Covers: the deterministic clarity metrics (clear vs. dense prose), the stylometric
AI-likelihood estimate (AI-tell text scores higher than plain), the pure aggregation
(distribution, marker vs. estimate counts, empty→zeros), the deterministic fallback
coaching, the LLM insights path (mocked, happy + fallback), the graceful page-collection
fan-out (skip/coverage/swallow, never raises), and the run_doc_quality orchestrator.
"""

from __future__ import annotations

from yeaboi.analysis.doc_quality import (
    _ai_likelihood,
    _clarity_metrics,
    _fallback_doc_quality_insights,
    aggregate_doc_quality,
    collect_doc_pages,
    generate_doc_quality_insights,
    run_doc_quality,
)
from yeaboi.team_profile import DocQualitySignal

# A plain, human, clear paragraph — short sentences, contractions, no AI tells.
_CLEAR_TEXT = (
    "# Onboarding\n\n"
    "Welcome to the team. Here's how to set up.\n\n"
    "- Clone the repo.\n"
    "- Run the setup script.\n"
    "- Ask if you're stuck.\n\n"
    "That's it. You're ready to go."
)

# A dense, jargon-heavy wall of one very long sentence.
_DENSE_TEXT = (
    "Notwithstanding the aforementioned architectural considerations, the comprehensive "
    "instrumentation subsystem necessitates meticulous reconfiguration across heterogeneous "
    "deployment environments whilst simultaneously accommodating the multifarious "
    "interdependencies inherent to distributed computational infrastructures and their "
    "concomitant orchestration frameworks, thereby precipitating substantial reconsideration."
)

# Prose loaded with classic AI-tell connectors and em-dashes.
_AI_TELL_TEXT = (
    "Moreover, it is worth noting that this approach will seamlessly leverage a robust, "
    "holistic framework — furthermore, it is important to note the paramount role of "
    "streamlined processes. Additionally, this serves to facilitate a testament to "
    "excellence. In conclusion, we delve into the realm of possibility — notably underscoring "
    "the crucial nature of the endeavour. Furthermore, this holistic tapestry is paramount."
)


class TestClarityMetrics:
    def test_clear_scores_higher_than_dense(self):
        clear = _clarity_metrics(_CLEAR_TEXT)["clarity"]
        dense = _clarity_metrics(_DENSE_TEXT)["clarity"]
        assert clear > dense
        assert clear >= 60  # plain-English band

    def test_empty_text_is_zero(self):
        m = _clarity_metrics("")
        assert m["clarity"] == 0.0
        assert m["word_count"] == 0

    def test_reports_structure(self):
        m = _clarity_metrics(_CLEAR_TEXT)
        assert m["heading_count"] >= 1
        assert m["has_lists"] is True

    def test_long_sentence_pct(self):
        m = _clarity_metrics(_DENSE_TEXT)
        assert m["long_sentence_pct"] > 0


class TestAiLikelihood:
    def test_ai_tell_scores_higher_than_plain(self):
        assert _ai_likelihood(_AI_TELL_TEXT) > _ai_likelihood(_CLEAR_TEXT)

    def test_ai_tell_crosses_likely_threshold(self):
        assert _ai_likelihood(_AI_TELL_TEXT) >= 55

    def test_plain_text_low(self):
        assert _ai_likelihood(_CLEAR_TEXT) < 40

    def test_empty_is_zero(self):
        assert _ai_likelihood("") == 0.0


class TestAggregate:
    def _pages(self):
        return [
            {"platform": "confluence", "title": "Clear one", "text": _CLEAR_TEXT},
            {"platform": "confluence", "title": "Dense one", "text": _DENSE_TEXT},
            {"platform": "notion", "title": "AI one", "text": _AI_TELL_TEXT},
        ]

    def test_counts_and_distribution(self):
        sig = aggregate_doc_quality(self._pages())
        assert sig.pages_scanned == 3
        assert set(sig.platforms_scanned) == {"confluence", "notion"}
        assert sig.clear_pages + sig.mixed_pages + sig.unclear_pages == 3
        assert dict(sig.per_platform) == {"confluence": 2, "notion": 1}
        assert sig.is_ai_estimate is True

    def test_ai_estimate_flags_the_ai_page(self):
        sig = aggregate_doc_quality(self._pages())
        assert sig.likely_ai_pages >= 1
        assert sig.avg_ai_likelihood > 0

    def test_explicit_marker_counted_as_lower_bound(self):
        disclosed = "Draft notes. Co-Authored-By: Claude <noreply@anthropic.com>"
        pages = [
            {"platform": "notion", "title": "Disclosed", "text": disclosed},
            {"platform": "notion", "title": "Plain", "text": _CLEAR_TEXT},
        ]
        sig = aggregate_doc_quality(pages)
        assert sig.ai_marked_pages == 1

    def test_flagged_pages_populated(self):
        sig = aggregate_doc_quality(self._pages())
        # The dense page (low clarity) and/or the AI page should surface as call-outs.
        assert sig.flagged_pages
        titles = {t for t, _ in sig.flagged_pages}
        assert "Dense one" in titles or "AI one" in titles

    def test_empty_returns_zeros(self):
        sig = aggregate_doc_quality([])
        assert sig == DocQualitySignal()
        assert sig.pages_scanned == 0


class TestFallbackInsights:
    def test_all_categories_non_empty_low_clarity(self):
        sig = DocQualitySignal(
            pages_scanned=5, avg_clarity=42.0, unclear_pages=2, avg_ai_likelihood=60.0, likely_ai_pages=2
        )
        out = _fallback_doc_quality_insights(sig)
        assert all(out[c] for c in ("start", "stop", "keep", "try"))

    def test_all_categories_non_empty_empty_signal(self):
        out = _fallback_doc_quality_insights(DocQualitySignal())
        assert all(out[c] for c in ("start", "stop", "keep", "try"))

    def test_high_ai_estimate_triggers_stop_with_estimate_framing(self):
        sig = DocQualitySignal(pages_scanned=4, avg_clarity=70.0, avg_ai_likelihood=70.0, likely_ai_pages=3)
        out = _fallback_doc_quality_insights(sig)
        blob = " ".join(it["detail"] + it["evidence"] for it in out["stop"]).lower()
        assert "estimate" in blob  # never asserts detection

    def test_cites_least_clear_page_with_link(self):
        sig = DocQualitySignal(pages_scanned=3, avg_clarity=45.0, unclear_pages=1)
        samples = [
            {"title": "Clear one", "platform": "notion", "clarity": 80, "ai_likelihood": 5, "url": "u1"},
            {"title": "Dense one", "platform": "confluence", "clarity": 25, "ai_likelihood": 5, "url": "u2"},
        ]
        out = _fallback_doc_quality_insights(sig, samples)
        tighten = next(it for it in out["start"] if "Tighten" in it["title"])
        assert "Dense one" in tighten["evidence"]  # the least-clear page
        assert tighten["link"] == "u2"


class _FakeResp:
    def __init__(self, content):
        self.content = content


class TestGenerateInsights:
    _SIG = DocQualitySignal(
        pages_scanned=6,
        platforms_scanned=("confluence", "notion"),
        avg_clarity=54.0,
        clear_pages=2,
        mixed_pages=2,
        unclear_pages=2,
        avg_ai_likelihood=58.0,
        likely_ai_pages=3,
        ai_marked_pages=1,
        per_platform=(("confluence", 4), ("notion", 2)),
        flagged_pages=(("Onboarding", "clarity 30/100 — dense or long-winded"),),
    )

    def test_happy_path_parses_json(self, monkeypatch):
        payload = (
            '{"start": [{"title": "Tighten docs", "detail": "d", "evidence": "e"}], '
            '"stop": [{"title": "Stop walls", "detail": "d", "evidence": "e"}], '
            '"keep": [{"title": "Keep clarity", "detail": "d", "evidence": "e"}], '
            '"try": [{"title": "Try templates", "detail": "d", "evidence": "e"}]}'
        )
        monkeypatch.setattr("yeaboi.tools.team_learning._llm_invoke", lambda *a, **k: _FakeResp(payload))
        out = generate_doc_quality_insights(self._SIG, {})
        assert out["start"][0]["title"] == "Tighten docs"
        assert all(out[c] for c in ("start", "stop", "keep", "try"))

    def test_code_fence_stripped(self, monkeypatch):
        body = '{"start": [{"title": "T", "detail": "d", "evidence": "e"}], "stop": [], "keep": [], "try": []}'
        payload = f"```json\n{body}\n```"
        monkeypatch.setattr("yeaboi.tools.team_learning._llm_invoke", lambda *a, **k: _FakeResp(payload))
        out = generate_doc_quality_insights(self._SIG, {})
        assert out["start"][0]["title"] == "T"
        # Empty categories fall back to the deterministic skeleton, never empty.
        assert all(out[c] for c in ("start", "stop", "keep", "try"))

    def test_llm_failure_falls_back(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("no llm")

        monkeypatch.setattr("yeaboi.tools.team_learning._llm_invoke", boom)
        out = generate_doc_quality_insights(self._SIG, {})
        assert all(out[c] for c in ("start", "stop", "keep", "try"))

    def test_link_validated_against_page_urls(self, monkeypatch):
        good = "https://notion.so/page-123"
        payload = (
            f'{{"start": [{{"title": "Real", "detail": "d", "evidence": "e", "link": "{good}"}}], '
            '"stop": [{"title": "Fake", "detail": "d", "evidence": "e", "link": "https://evil.example/x"}], '
            '"keep": [{"title": "K", "detail": "d", "evidence": "e"}], '
            '"try": [{"title": "T", "detail": "d", "evidence": "e"}]}'
        )
        monkeypatch.setattr("yeaboi.tools.team_learning._llm_invoke", lambda *a, **k: _FakeResp(payload))
        examples = {"samples": [{"url": good, "title": "x", "platform": "notion", "clarity": 40, "ai_likelihood": 20}]}
        out = generate_doc_quality_insights(self._SIG, examples)
        assert out["start"][0]["link"] == good
        assert "link" not in out["stop"][0]


class TestCollectDocPages:
    def test_no_config_records_coverage_gaps(self, monkeypatch):
        monkeypatch.setattr("yeaboi.config.get_confluence_token", lambda: None)
        monkeypatch.setattr("yeaboi.config.get_confluence_base_url", lambda: None)
        monkeypatch.setattr("yeaboi.config.get_notion_token", lambda: None)
        pages, platforms, coverage = collect_doc_pages("jira", "PROJ")
        assert pages == []
        assert platforms == []
        assert any("confluence" in c for c in coverage)
        assert any("notion" in c for c in coverage)

    def test_confluence_pages_tagged_and_deduped(self, monkeypatch):
        monkeypatch.setattr("yeaboi.config.get_confluence_token", lambda: "tok")
        monkeypatch.setattr("yeaboi.config.get_confluence_base_url", lambda: "https://x.atlassian.net/wiki")
        monkeypatch.setattr("yeaboi.config.get_notion_token", lambda: None)
        # Two recent items for the SAME page id (Confluence emits one per editor) → one read.
        monkeypatch.setattr(
            "yeaboi.tools.confluence.confluence_recent_pages",
            lambda days=1: [
                {"key": "123", "title": "Guide", "author": "A", "url": "u", "timestamp": "t"},
                {"key": "123", "title": "Guide", "author": "B", "url": "u", "timestamp": "t"},
            ],
        )
        reads: list[str] = []

        def _read(page_id="", max_chars=0):
            reads.append(page_id)
            return {"title": "Guide", "text": _CLEAR_TEXT, "truncated": False, "error": ""}

        monkeypatch.setattr("yeaboi.tools.confluence.confluence_read_page_text", _read)
        pages, platforms, coverage = collect_doc_pages("jira", "PROJ")
        assert len(pages) == 1  # deduped
        assert reads == ["123"]  # only one body read
        assert pages[0]["platform"] == "confluence"
        assert platforms == ["confluence"]

    def test_source_error_recorded_not_raised(self, monkeypatch):
        monkeypatch.setattr("yeaboi.config.get_confluence_token", lambda: "tok")
        monkeypatch.setattr("yeaboi.config.get_confluence_base_url", lambda: "https://x/wiki")
        monkeypatch.setattr("yeaboi.config.get_notion_token", lambda: None)

        def boom(days=1):
            raise RuntimeError("401 Unauthorized")

        monkeypatch.setattr("yeaboi.tools.confluence.confluence_recent_pages", boom)
        pages, platforms, coverage = collect_doc_pages("jira", "PROJ")
        assert pages == []
        assert any("confluence: error" in c for c in coverage)

    def test_empty_text_pages_dropped(self, monkeypatch):
        monkeypatch.setattr("yeaboi.config.get_confluence_token", lambda: None)
        monkeypatch.setattr("yeaboi.config.get_confluence_base_url", lambda: None)
        monkeypatch.setattr("yeaboi.config.get_notion_token", lambda: "tok")
        monkeypatch.setattr(
            "yeaboi.tools.notion.notion_recent_pages",
            lambda days=1: [{"key": "p1", "title": "Empty", "author": "A", "url": "u", "timestamp": "t"}],
        )
        monkeypatch.setattr(
            "yeaboi.tools.notion.notion_read_page_text",
            lambda page_id, max_chars=0: {"title": "Empty", "text": "   ", "truncated": False, "error": ""},
        )
        pages, platforms, coverage = collect_doc_pages("jira", "PROJ")
        assert pages == []  # blank body dropped
        assert any("notion: no pages" in c for c in coverage)


class TestRunDocQuality:
    def test_aggregates_collected_pages(self, monkeypatch):
        monkeypatch.setattr(
            "yeaboi.analysis.doc_quality.collect_doc_pages",
            lambda source, project: (
                [
                    {"platform": "confluence", "title": "Clear", "text": _CLEAR_TEXT},
                    {"platform": "notion", "title": "AI", "text": _AI_TELL_TEXT},
                ],
                ["confluence", "notion"],
                [],
            ),
        )
        signal, blob = run_doc_quality("jira", "PROJ")
        assert signal.pages_scanned == 2
        assert blob["summary"]["pages_scanned"] == 2
        # Samples carry titles/scores only — never page bodies.
        assert blob["samples"]
        assert all("text" not in s for s in blob["samples"])

    def test_collect_failure_returns_empty_signal(self, monkeypatch):
        def boom(source, project):
            raise RuntimeError("kaboom")

        monkeypatch.setattr("yeaboi.analysis.doc_quality.collect_doc_pages", boom)
        signal, blob = run_doc_quality("jira", "PROJ")
        assert signal == DocQualitySignal()
        assert blob["coverage"] == ["doc-quality scan failed"]
