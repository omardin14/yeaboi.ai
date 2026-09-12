"""Tests for src/yeaboi/app/_context_body.py — the three context keys every run body may carry."""

from __future__ import annotations

import pytest

from yeaboi.app._context_body import MAX_PROJECT_LABEL, MAX_TAGS, read_context
from yeaboi.app.router import HTTPError
from yeaboi.context.scope import ContextScope


class TestReadContext:
    def test_an_empty_body_reads_as_today(self):
        assert read_context({}) == (None, "", ())
        assert read_context({"context": "", "project_label": "", "tags": []}) == (None, "", ())

    def test_a_spec_string_and_a_dict_both_parse(self):
        scope, _label, _tags = read_context({"context": "standup,retro:1@2sprints"})
        assert isinstance(scope, ContextScope) and scope.wants("standup") and not scope.wants("plan")
        scope, _label, _tags = read_context({"context": {"sources": ["retro"], "window": {"kind": "month"}}})
        assert scope.sources == frozenset({"retro"}) and scope.window.kind == "month"

    def test_a_typo_is_a_400_naming_the_valid_sources(self):
        with pytest.raises(HTTPError) as exc:
            read_context({"context": "stanup"})
        assert exc.value.code == 400 and "standup" in exc.value.message

    def test_labels_and_tags_are_normalised(self):
        _scope, label, tags = read_context({"project_label": "  Apollo   Two ", "tags": ["Team A", "q3", "q3", ""]})
        assert label == "Apollo Two" and tags == ("team-a", "q3")

    @pytest.mark.parametrize(
        "payload",
        [
            {"project_label": 3},
            {"project_label": "x" * (MAX_PROJECT_LABEL + 1)},
            {"tags": "q3"},
            {"tags": [1]},
            {"tags": ["t"] * (MAX_TAGS + 1)},
            {"tags": ["x" * 41]},
        ],
    )
    def test_malformed_labels_are_400s(self, payload):
        with pytest.raises(HTTPError) as exc:
            read_context(payload)
        assert exc.value.code == 400
