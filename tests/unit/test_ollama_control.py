"""Tests for the stop-Ollama-on-exit helpers (`ollama_control`).

Covers the exit-prompt gate (`should_offer_ollama_stop`) and the smart-stop
(`stop_ollama_server`) — brew-managed full stop vs. model-unload fallback —
all of which must be never-raising so quitting the app can't be blocked.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from yeaboi import ollama_control


class TestIsLocalhost:
    @pytest.mark.parametrize(
        "url",
        ["http://localhost:11434", "http://127.0.0.1:11434", "http://[::1]:11434"],
    )
    def test_local_urls_true(self, url):
        assert ollama_control._is_localhost(url) is True

    @pytest.mark.parametrize(
        "url",
        ["http://192.168.1.5:11434", "https://ollama.example.com", "http://10.0.0.2:11434"],
    )
    def test_remote_urls_false(self, url):
        assert ollama_control._is_localhost(url) is False


class TestIsOllamaInstalled:
    def test_true_when_binary_on_path(self, monkeypatch):
        monkeypatch.setattr(ollama_control.shutil, "which", lambda name: "/usr/local/bin/ollama")
        assert ollama_control.is_ollama_installed() is True

    def test_false_when_binary_absent(self, monkeypatch):
        monkeypatch.setattr(ollama_control.shutil, "which", lambda name: None)
        assert ollama_control.is_ollama_installed() is False


class TestShouldOfferOllamaStop:
    def _patch(self, monkeypatch, *, provider="ollama", base="http://localhost:11434", status=200, raise_probe=False):
        import yeaboi.config as config

        monkeypatch.setattr(config, "get_llm_provider", lambda: provider)
        monkeypatch.setattr(config, "get_ollama_base_url", lambda: base)

        import httpx

        def fake_get(url, timeout=None):
            if raise_probe:
                raise httpx.ConnectError("refused")
            return SimpleNamespace(status_code=status)

        monkeypatch.setattr(httpx, "get", fake_get)

    def test_true_when_ollama_localhost_reachable(self, monkeypatch):
        self._patch(monkeypatch)
        assert ollama_control.should_offer_ollama_stop() is True

    def test_false_for_cloud_provider(self, monkeypatch):
        self._patch(monkeypatch, provider="anthropic")
        assert ollama_control.should_offer_ollama_stop() is False

    def test_false_for_non_localhost(self, monkeypatch):
        self._patch(monkeypatch, base="http://192.168.1.5:11434")
        assert ollama_control.should_offer_ollama_stop() is False

    def test_false_when_server_down_no_raise(self, monkeypatch):
        self._patch(monkeypatch, raise_probe=True)
        assert ollama_control.should_offer_ollama_stop() is False

    def test_false_on_non_200(self, monkeypatch):
        self._patch(monkeypatch, status=500)
        assert ollama_control.should_offer_ollama_stop() is False


class TestStopOllamaServer:
    def test_brew_managed_full_stop(self, monkeypatch):
        monkeypatch.setattr(ollama_control.shutil, "which", lambda name: "/opt/homebrew/bin/brew")

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if "info" in cmd:
                return SimpleNamespace(returncode=0, stdout='[{"name":"ollama","status":"started"}]', stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(ollama_control.subprocess, "run", fake_run)
        stopped, msg = ollama_control.stop_ollama_server()
        assert stopped is True
        assert "brew" in msg.lower()
        assert ["brew", "services", "stop", "ollama"] in calls

    def test_unload_fallback_when_no_brew(self, monkeypatch):
        monkeypatch.setattr(ollama_control.shutil, "which", lambda name: None)

        posted = {}

        import httpx

        def fake_post(url, json=None, timeout=None):
            posted["url"] = url
            posted["json"] = json
            return SimpleNamespace(status_code=200)

        monkeypatch.setattr(httpx, "post", fake_post)
        monkeypatch.setenv("LLM_MODEL", "qwen3:8b")
        stopped, msg = ollama_control.stop_ollama_server()
        assert stopped is False
        assert posted["json"]["keep_alive"] == 0
        assert "unloaded" in msg.lower()

    def test_brew_not_started_falls_through_to_unload(self, monkeypatch):
        monkeypatch.setattr(ollama_control.shutil, "which", lambda name: "/opt/homebrew/bin/brew")
        monkeypatch.setattr(
            ollama_control.subprocess,
            "run",
            lambda cmd, **kw: SimpleNamespace(returncode=0, stdout='[{"status":"stopped"}]', stderr=""),
        )
        import httpx

        monkeypatch.setattr(httpx, "post", lambda *a, **kw: SimpleNamespace(status_code=200))
        stopped, msg = ollama_control.stop_ollama_server()
        assert stopped is False
        assert "unloaded" in msg.lower()

    def test_subprocess_timeout_never_raises(self, monkeypatch):
        monkeypatch.setattr(ollama_control.shutil, "which", lambda name: "/opt/homebrew/bin/brew")

        def boom(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 10)

        monkeypatch.setattr(ollama_control.subprocess, "run", boom)
        import httpx

        monkeypatch.setattr(httpx, "post", lambda *a, **kw: SimpleNamespace(status_code=200))
        stopped, msg = ollama_control.stop_ollama_server()
        # brew probe failed → falls through to unload, still no raise
        assert stopped is False
        assert isinstance(msg, str)

    def test_all_paths_fail_returns_message(self, monkeypatch):
        monkeypatch.setattr(ollama_control.shutil, "which", lambda name: None)
        import httpx

        def boom(*a, **kw):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(httpx, "post", boom)
        stopped, msg = ollama_control.stop_ollama_server()
        assert stopped is False
        assert "could not stop" in msg.lower()
