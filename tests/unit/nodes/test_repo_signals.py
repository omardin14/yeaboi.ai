"""Tests for repo_signals — deterministic repository/tech signals for the smart
intake (tech-stack + integration suggestion, low-code detection).

See README: "Project Intake Questionnaire" — smart intake.
"""

from unittest.mock import MagicMock

from yeaboi.agent.repo_signals import (
    INTEGRATION_SDK_MARKERS,
    LOW_CODE_MARKERS,
    RepoSignals,
    _detect_low_code,
    _parse_key_files,
    _parse_languages,
    _parse_total_files,
    analyze_context,
    scan_repo_signals,
)
from yeaboi.agent.state import QuestionnaireState

# A github_read_repo / read_codebase style summary — the two tools share format.
_GH_SUMMARY = """Repository: acme/storefront
Default branch: main

File tree (top level):
  src/
  content/

Key files detected:
  package.json
  Dockerfile

Languages:
  TypeScript: 68.0%
  CSS: 32.0%

Stars: 4  Forks: 1  Open issues: 3"""

_LOCAL_SUMMARY = """Local repository: /tmp/site
Total files scanned: 3

File tree:
  content/

Key files detected:
  README.md"""


class TestParsers:
    def test_parse_languages(self):
        assert _parse_languages(_GH_SUMMARY) == ["TypeScript", "CSS"]

    def test_parse_languages_absent(self):
        assert _parse_languages("Repository: x\n\nNo languages here") == []

    def test_parse_key_files(self):
        assert _parse_key_files(_GH_SUMMARY) == ["package.json", "Dockerfile"]

    def test_parse_total_files(self):
        assert _parse_total_files(_LOCAL_SUMMARY) == 3
        assert _parse_total_files(_GH_SUMMARY) is None


class TestAnalyzeContextStack:
    def test_detected_stack_from_languages_and_key_files(self):
        s = analyze_context(_GH_SUMMARY, description="storefront", tech_stack="TypeScript")
        # Languages first, then key-file tools (Docker).
        assert "TypeScript" in s.detected_stack
        assert "CSS" in s.detected_stack
        assert "Docker" in s.detected_stack

    def test_frameworks_and_integrations_from_manifests(self):
        manifests = {"package.json": '{"dependencies": {"next": "14", "stripe": "12", "@sendgrid/mail": "7"}}'}
        s = analyze_context(_GH_SUMMARY, manifests=manifests, source="github")
        assert "Next.js" in s.detected_stack  # framework from manifest
        assert "Stripe" in s.integrations
        assert "SendGrid" in s.integrations

    def test_detected_stack_deduplicated(self):
        # "TypeScript" appears as a language; ensure no duplicates in output.
        s = analyze_context(_GH_SUMMARY)
        assert s.detected_stack.count("TypeScript") == 1

    def test_empty_context_yields_empty_stack(self):
        s = analyze_context("", description="", tech_stack="")
        assert s.detected_stack == []
        assert s.integrations == []
        assert s.low_code is False


class TestLowCodeDetection:
    def test_marker_in_description(self):
        low, reasons = _detect_low_code(
            description="Set up a Zapier + Webflow content site",
            tech_stack="",
            languages=[],
            key_files=[],
            total_files=None,
        )
        assert low is True
        assert any("zapier" in r.lower() or "webflow" in r.lower() for r in reasons)

    def test_marker_multiword_phrase(self):
        low, _ = _detect_low_code(
            description="A Power Platform automation",
            tech_stack="",
            languages=[],
            key_files=[],
            total_files=None,
        )
        assert low is True

    def test_no_languages_but_scanned(self):
        low, reasons = _detect_low_code(
            description="docs site",
            tech_stack="",
            languages=[],
            key_files=["README.md"],
            total_files=None,
        )
        assert low is True
        assert any("no source-code" in r for r in reasons)

    def test_very_small_codebase(self):
        low, reasons = _detect_low_code(
            description="tiny",
            tech_stack="",
            languages=["Python"],
            key_files=["pyproject.toml"],
            total_files=3,
        )
        assert low is True
        assert any("very small" in r for r in reasons)

    def test_healthy_repo_not_low_code(self):
        low, reasons = _detect_low_code(
            description="A FastAPI backend service",
            tech_stack="Python, FastAPI, PostgreSQL",
            languages=["Python", "Shell"],
            key_files=["pyproject.toml", "Dockerfile"],
            total_files=120,
        )
        assert low is False
        assert reasons == []

    def test_marker_word_boundary_no_false_positive(self):
        # "wix" must not match inside an unrelated word like "wixel".
        low, _ = _detect_low_code(
            description="Building a wixel firmware toolchain",
            tech_stack="",
            languages=["C"],
            key_files=["Makefile"],
            total_files=200,
        )
        assert low is False

    def test_analyze_context_low_code_via_description(self):
        s = analyze_context("", description="WordPress marketing site", tech_stack="")
        assert s.low_code is True


class TestVocabularies:
    def test_markers_are_lowercase(self):
        assert all(m == m.lower() for m in LOW_CODE_MARKERS)

    def test_integration_markers_map_to_names(self):
        assert INTEGRATION_SDK_MARKERS["stripe"] == "Stripe"
        assert INTEGRATION_SDK_MARKERS["boto3"] == "AWS"


class TestScanRepoSignals:
    """The graceful I/O entry — no target → no-op; description markers still apply."""

    def test_no_repo_no_target_skips_gracefully(self):
        qs = QuestionnaireState()
        qs.answers[1] = "A plain internal tool"
        raw, signals, status = scan_repo_signals(qs)
        assert raw is None
        assert isinstance(signals, RepoSignals)
        assert status["status"] == "skipped"

    def test_description_markers_flag_low_code_without_repo(self):
        qs = QuestionnaireState()
        qs.answers[1] = "Configure a Salesforce workflow, no custom code"
        raw, signals, _status = scan_repo_signals(qs)
        assert raw is None
        assert signals.low_code is True

    def test_github_scan_applies_signals(self, monkeypatch):
        qs = QuestionnaireState()
        qs.answers[1] = "A storefront"
        qs.answers[16] = "GitHub"
        qs.answers[17] = "https://github.com/acme/storefront"

        fake_repo = MagicMock()
        fake_repo.invoke.return_value = _GH_SUMMARY
        fake_file = MagicMock()
        fake_file.invoke.return_value = '{"dependencies": {"stripe": "12"}}'
        monkeypatch.setattr("yeaboi.tools.github.github_read_repo", fake_repo)
        monkeypatch.setattr("yeaboi.tools.github.github_read_file", fake_file)

        raw, signals, status = scan_repo_signals(qs)
        assert raw == _GH_SUMMARY
        assert status["status"] == "success"
        assert "TypeScript" in signals.detected_stack
        assert "Stripe" in signals.integrations
        assert signals.source == "github"

    def test_github_error_result_degrades(self, monkeypatch):
        qs = QuestionnaireState()
        qs.answers[17] = "https://github.com/acme/missing"
        fake_repo = MagicMock()
        fake_repo.invoke.return_value = "Error: 404 Not Found"
        monkeypatch.setattr("yeaboi.tools.github.github_read_repo", fake_repo)

        raw, signals, _status = scan_repo_signals(qs)
        assert raw is None  # error string is not treated as context
        assert signals.detected_stack == []

    def test_scan_exception_never_raises(self, monkeypatch):
        qs = QuestionnaireState()
        qs.answers[17] = "https://github.com/acme/boom"
        fake_repo = MagicMock()
        fake_repo.invoke.side_effect = RuntimeError("network down")
        monkeypatch.setattr("yeaboi.tools.github.github_read_repo", fake_repo)

        raw, signals, status = scan_repo_signals(qs)  # must not raise
        assert raw is None
        assert status["status"] == "error"
