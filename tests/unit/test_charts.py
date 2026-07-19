"""Tests for charts.py — optional matplotlib chart generation for exports."""

from __future__ import annotations

import builtins

import pytest

from yeaboi.charts import charts_available, delivered_chart, velocity_chart


def _block_matplotlib(monkeypatch):
    """Make `import matplotlib` fail to simulate the extra not being installed."""
    real_import = builtins.__import__

    def _imp(name, *args, **kwargs):
        if name == "matplotlib" or name.startswith("matplotlib."):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _imp)


class TestAvailability:
    def test_available_with_dev_extra(self):
        # matplotlib is in the dev extra, so CI/dev envs have it.
        assert charts_available() is True

    def test_unavailable_when_import_blocked(self, monkeypatch):
        _block_matplotlib(monkeypatch)
        assert charts_available() is False


class TestVelocityChart:
    def test_writes_png(self, tmp_path):
        pytest.importorskip("matplotlib")
        out = velocity_chart([("Sprint 1", 20, 18), ("Sprint 2", 22, 22)], tmp_path / "v.png")
        assert out == tmp_path / "v.png"
        data = out.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_empty_rows_returns_none(self, tmp_path):
        assert velocity_chart([], tmp_path / "v.png") is None
        assert not (tmp_path / "v.png").exists()

    def test_missing_matplotlib_returns_none(self, monkeypatch, tmp_path):
        _block_matplotlib(monkeypatch)
        assert velocity_chart([("S1", 10, 8)], tmp_path / "v.png") is None

    def test_render_error_returns_none(self, monkeypatch, tmp_path):
        pytest.importorskip("matplotlib")
        # A directory path can't be written as a file → savefig raises inside.
        target = tmp_path / "as-dir.png"
        target.mkdir()
        assert velocity_chart([("S1", 10, 8)], target) is None


class TestDeliveredChart:
    def test_writes_png(self, tmp_path):
        pytest.importorskip("matplotlib")
        out = delivered_chart([("Story", 7), ("Bug", 3)], tmp_path / "d.png")
        assert out == tmp_path / "d.png"
        assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    def test_empty_counts_returns_none(self, tmp_path):
        assert delivered_chart([], tmp_path / "d.png") is None

    def test_missing_matplotlib_returns_none(self, monkeypatch, tmp_path):
        _block_matplotlib(monkeypatch)
        assert delivered_chart([("Story", 7)], tmp_path / "d.png") is None
