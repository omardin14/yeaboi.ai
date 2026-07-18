"""Tests for the bundled changelog loader (src/yeaboi/changelog.py)."""

from __future__ import annotations

import re

import pytest

from yeaboi import changelog
from yeaboi.changelog import (
    AREA_COLORS,
    VALID_AREAS,
    ChangelogEntry,
    ChangelogHighlight,
    load_changelog,
)


class _FakeTraversable:
    def __init__(self, text: str | None):
        self._text = text

    def __truediv__(self, name: str):
        return self

    def read_text(self, encoding: str = "utf-8") -> str:
        if self._text is None:
            raise FileNotFoundError("changelog_data.json")
        return self._text


def _patch_data(monkeypatch, text: str | None):
    monkeypatch.setattr(changelog.resources, "files", lambda pkg: _FakeTraversable(text))


class TestBundledData:
    """Integrity checks against the real shipped changelog_data.json."""

    def test_loads_real_file(self):
        entries = load_changelog()
        assert entries, "bundled changelog should not be empty"
        assert all(isinstance(e, ChangelogEntry) for e in entries)

    def test_newest_first(self):
        versions = [tuple(int(p) for p in e.version.split(".")) for e in load_changelog()]
        assert versions == sorted(versions, reverse=True)

    def test_all_areas_valid(self):
        for entry in load_changelog():
            for hl in entry.highlights:
                assert hl.areas, f"{entry.version}: highlight without areas"
                assert set(hl.areas) <= VALID_AREAS

    def test_dates_iso(self):
        for entry in load_changelog():
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry.date), entry.version

    def test_every_entry_has_summary_and_highlights(self):
        for entry in load_changelog():
            assert entry.summary, entry.version
            assert entry.highlights, entry.version


class TestGracefulLoading:
    def test_missing_file_returns_empty(self, monkeypatch):
        _patch_data(monkeypatch, None)
        assert load_changelog() == []

    def test_corrupt_json_returns_empty(self, monkeypatch):
        _patch_data(monkeypatch, "{not json")
        assert load_changelog() == []

    def test_non_dict_root_returns_empty(self, monkeypatch):
        _patch_data(monkeypatch, "[1, 2, 3]")
        assert load_changelog() == []

    def test_malformed_entries_skipped(self, monkeypatch):
        _patch_data(
            monkeypatch,
            '{"entries": [{"version": "1.0.0", "summary": "ok", "highlights": []},'
            ' {"no_version": true}, "just-a-string", {"version": ""}]}',
        )
        entries = load_changelog()
        assert [e.version for e in entries] == ["1.0.0"]

    def test_unknown_area_coerced_to_general(self, monkeypatch):
        _patch_data(
            monkeypatch,
            '{"entries": [{"version": "1.0.0", "highlights": [{"text": "x", "areas": ["bogus", "planning"]}]}]}',
        )
        entries = load_changelog()
        assert entries[0].highlights[0].areas == ("general", "planning")

    def test_missing_areas_defaults_to_general(self, monkeypatch):
        _patch_data(monkeypatch, '{"entries": [{"version": "1.0.0", "highlights": [{"text": "x"}]}]}')
        assert load_changelog()[0].highlights[0].areas == ("general",)

    def test_highlight_without_text_skipped(self, monkeypatch):
        _patch_data(
            monkeypatch,
            '{"entries": [{"version": "1.0.0", "highlights": [{"areas": ["planning"]}, {"text": "kept"}]}]}',
        )
        highlights = load_changelog()[0].highlights
        assert [h.text for h in highlights] == ["kept"]


class TestAreaColors:
    def test_covers_all_valid_areas(self):
        assert set(AREA_COLORS) == set(VALID_AREAS)

    def test_all_rgb_strings(self):
        for color in AREA_COLORS.values():
            assert re.fullmatch(r"rgb\(\d{1,3},\d{1,3},\d{1,3}\)", color)


class TestDataclasses:
    def test_defaults_for_backward_compat(self):
        assert ChangelogEntry().version == ""
        assert ChangelogHighlight().areas == ()

    def test_frozen(self):
        entry = ChangelogEntry(version="1.0.0")
        with pytest.raises(AttributeError):
            entry.version = "2.0.0"  # type: ignore[misc]
