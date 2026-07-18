"""Tests for the OS clipboard image reader (yeaboi/clipboard.py).

All subprocess calls are mocked — no test touches the real clipboard.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from yeaboi import clipboard

# A tiny valid PNG header + filler — enough to assert bytes round-trip intact.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _proc(returncode=0, stdout=b""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=b"")


class TestMacOS:
    @pytest.fixture(autouse=True)
    def _darwin(self, monkeypatch):
        monkeypatch.setattr(clipboard.sys, "platform", "darwin")

    def test_osascript_png_hex_parses(self, monkeypatch):
        monkeypatch.setattr(clipboard.shutil, "which", lambda _: None)  # no pngpaste
        hex_dump = f"«data PNGf{PNG_BYTES.hex().upper()}»\n".encode()

        def fake_run(cmd, **kwargs):
            assert cmd[0] == "osascript"
            if "PNGf" in cmd[-1]:
                return _proc(0, hex_dump)
            return _proc(1)

        monkeypatch.setattr(clipboard.subprocess, "run", fake_run)
        assert clipboard.read_clipboard_image() == (PNG_BYTES, "image/png")

    def test_jpeg_fallback_when_png_coercion_fails(self, monkeypatch):
        monkeypatch.setattr(clipboard.shutil, "which", lambda _: None)
        jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 8
        hex_dump = f"«data JPEG{jpeg.hex()}»".encode()

        def fake_run(cmd, **kwargs):
            if "JPEG" in cmd[-1]:
                return _proc(0, hex_dump)
            return _proc(1)  # PNGf coercion fails ("Can't make ... into expected type")

        monkeypatch.setattr(clipboard.subprocess, "run", fake_run)
        assert clipboard.read_clipboard_image() == (jpeg, "image/jpeg")

    def test_pngpaste_fast_path_preferred(self, monkeypatch):
        monkeypatch.setattr(clipboard.shutil, "which", lambda name: "/opt/bin/pngpaste")
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd[0])
            return _proc(0, PNG_BYTES)

        monkeypatch.setattr(clipboard.subprocess, "run", fake_run)
        assert clipboard.read_clipboard_image() == (PNG_BYTES, "image/png")
        assert calls == ["pngpaste"]  # osascript never invoked

    def test_non_image_clipboard_returns_none(self, monkeypatch):
        monkeypatch.setattr(clipboard.shutil, "which", lambda _: None)
        monkeypatch.setattr(clipboard.subprocess, "run", lambda cmd, **kw: _proc(1))
        assert clipboard.read_clipboard_image() is None

    def test_timeout_returns_none(self, monkeypatch):
        monkeypatch.setattr(clipboard.shutil, "which", lambda _: None)

        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 10))

        monkeypatch.setattr(clipboard.subprocess, "run", fake_run)
        assert clipboard.read_clipboard_image() is None

    def test_missing_binary_returns_none(self, monkeypatch):
        monkeypatch.setattr(clipboard.shutil, "which", lambda _: None)

        def fake_run(cmd, **kwargs):
            raise FileNotFoundError(cmd[0])

        monkeypatch.setattr(clipboard.subprocess, "run", fake_run)
        assert clipboard.read_clipboard_image() is None

    def test_malformed_hex_returns_none(self, monkeypatch):
        monkeypatch.setattr(clipboard.shutil, "which", lambda _: None)
        monkeypatch.setattr(clipboard.subprocess, "run", lambda cmd, **kw: _proc(0, "«data PNGfZZNOTHEX»".encode()))
        assert clipboard.read_clipboard_image() is None


class TestLinux:
    @pytest.fixture(autouse=True)
    def _linux(self, monkeypatch):
        monkeypatch.setattr(clipboard.sys, "platform", "linux")

    def test_wl_paste_preferred_over_xclip(self, monkeypatch):
        monkeypatch.setattr(clipboard.shutil, "which", lambda name: f"/usr/bin/{name}")
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd[0])
            return _proc(0, PNG_BYTES)

        monkeypatch.setattr(clipboard.subprocess, "run", fake_run)
        assert clipboard.read_clipboard_image() == (PNG_BYTES, "image/png")
        assert calls == ["wl-paste"]

    def test_falls_back_to_xclip_when_wl_paste_missing(self, monkeypatch):
        monkeypatch.setattr(clipboard.shutil, "which", lambda name: None if name == "wl-paste" else f"/usr/bin/{name}")
        monkeypatch.setattr(clipboard.subprocess, "run", lambda cmd, **kw: _proc(0, PNG_BYTES))
        assert clipboard.read_clipboard_image() == (PNG_BYTES, "image/png")

    def test_no_helpers_installed_returns_none(self, monkeypatch):
        monkeypatch.setattr(clipboard.shutil, "which", lambda _: None)
        assert clipboard.read_clipboard_image() is None


def test_unsupported_platform_returns_none(monkeypatch):
    monkeypatch.setattr(clipboard.sys, "platform", "win32")
    assert clipboard.read_clipboard_image() is None
