"""Unit tests for the pure (SDK-free) helpers in triage.py.

Run: uv run pytest automation/feedback_remediation/test_triage.py
(Not part of `make test`, which scopes to tests/ — this module lives beside the
automation script it covers.)
"""

from __future__ import annotations

import pytest
import triage


class TestShouldProcess:
    def test_fresh_feedback_is_processed(self):
        issue = {"author": {"login": "someuser"}, "labels": [{"name": "type:bug"}]}
        assert triage.should_process(issue) is True

    def test_already_triaged_is_skipped(self):
        issue = {"author": {"login": "someuser"}, "labels": [{"name": "triaged"}]}
        assert triage.should_process(issue) is False

    @pytest.mark.parametrize("bot", ["github-actions[bot]", "dependabot[bot]"])
    def test_bot_authored_is_skipped(self, bot):
        issue = {"author": {"login": bot}, "labels": []}
        assert triage.should_process(issue) is False

    @pytest.mark.parametrize("label", ["groomer-report", "flaky-test", "ci-sentinel", "ci-red-main"])
    def test_automation_issues_are_skipped(self, label):
        issue = {"author": {"login": "someuser"}, "labels": [{"name": label}]}
        assert triage.should_process(issue) is False

    def test_missing_author_and_labels(self):
        assert triage.should_process({}) is True


class TestTypeLabelFromTitle:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("[Bug] login crashes", "type:bug"),
            ("[Feature] add dark mode", "type:feature"),
            ("[Improvement] faster export", "type:improvement"),
            ("[Other] question about setup", "type:other"),
            ("[bug] lowercase prefix", "type:bug"),
            ("  [Bug] leading spaces", "type:bug"),
        ],
    )
    def test_known_prefixes(self, title, expected):
        assert triage.type_label_from_title(title) == expected

    def test_no_prefix_returns_none(self):
        assert triage.type_label_from_title("plain title, no prefix") is None

    def test_unknown_prefix_returns_none(self):
        assert triage.type_label_from_title("[Random] not a type") is None


class TestParseClassification:
    def test_plain_json(self):
        out = triage.parse_classification(
            '{"category": "Bug", "actionable": true, "confidence": "High", "reason": "x"}'
        )
        assert out == {"category": "bug", "actionable": True, "confidence": "high", "reason": "x"}

    def test_code_fenced_json(self):
        text = '```json\n{"category": "feature", "actionable": false, "confidence": "low", "reason": "y"}\n```'
        out = triage.parse_classification(text)
        assert out["category"] == "feature"
        assert out["actionable"] is False

    def test_missing_keys_get_safe_defaults(self):
        out = triage.parse_classification('{"category": "noise"}')
        assert out == {"category": "noise", "actionable": False, "confidence": "low", "reason": ""}

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError):
            triage.parse_classification("not json at all")


class TestBuildDigest:
    def test_lists_candidates_and_fixes(self):
        body = triage.build_digest(
            feature_candidates=[{"number": 5, "title": "add X"}],
            fixed=[{"number": 9, "title": "fix Y"}],
        )
        assert "#5 add X" in body
        assert "#9 fix Y" in body

    def test_empty_sections_say_none(self):
        body = triage.build_digest(feature_candidates=[], fixed=[])
        assert body.count("_none this week_") == 2
