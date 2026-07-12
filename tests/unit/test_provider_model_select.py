"""Tests for the LLM model-selection step of the provider setup wizard.

Covers:
- ``_verify_model`` live-validation per provider (happy + error paths, mocked).
- The two new screen builders (render, plaintext-not-masked, states).
- Data integrity: each card's default model matches ``_PROVIDER_DEFAULTS``.
- ``run_setup_wizard`` propagates the chosen model to ``LLM_MODEL``.
"""

from io import StringIO

import pytest
from rich.console import Console
from rich.panel import Panel

from scrum_agent.agent.llm import _PROVIDER_DEFAULTS
from scrum_agent.setup_wizard import _PROVIDERS, run_setup_wizard
from scrum_agent.ui.provider_select._constants import _PROVIDER_CARDS
from scrum_agent.ui.provider_select._verification import _verify_model
from scrum_agent.ui.provider_select.screens._screens import (
    _build_model_input_screen,
    _build_model_select_screen,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _card(provider_val: str) -> dict:
    return next(c for c in _PROVIDER_CARDS if c["provider_val"] == provider_val)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


def _render(panel: Panel) -> str:
    console = Console(file=StringIO(), width=80, highlight=False)
    console.print(panel)
    return console.file.getvalue()


# ---------------------------------------------------------------------------
# _verify_model — Anthropic
# ---------------------------------------------------------------------------


class TestVerifyModelAnthropic:
    def test_success(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(200))
        ok, _ = _verify_model(_card("anthropic"), "sk-ant-key", "claude-opus-4-8")
        assert ok is True

    def test_unknown_model_404(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(404))
        ok, msg = _verify_model(_card("anthropic"), "sk-ant-key", "claude-nope")
        assert ok is False
        assert "not" in msg.lower()

    def test_bad_request_surfaces_detail(self, monkeypatch):
        import httpx

        payload = {"error": {"message": "model: claude-nope is not supported"}}
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(400, payload))
        ok, msg = _verify_model(_card("anthropic"), "sk-ant-key", "claude-nope")
        assert ok is False
        assert "not supported" in msg

    def test_bad_credentials_401(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse(401))
        ok, msg = _verify_model(_card("anthropic"), "sk-ant-bad", "claude-opus-4-8")
        assert ok is False
        assert "Invalid" in msg

    def test_connection_error(self, monkeypatch):
        import httpx

        def _boom(*a, **kw):
            raise RuntimeError("network down")

        monkeypatch.setattr(httpx, "post", _boom)
        ok, msg = _verify_model(_card("anthropic"), "sk-ant-key", "claude-opus-4-8")
        assert ok is False
        assert "Connection error" in msg


# ---------------------------------------------------------------------------
# _verify_model — OpenAI / Google
# ---------------------------------------------------------------------------


class TestVerifyModelOpenAI:
    def test_success(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(200))
        ok, _ = _verify_model(_card("openai"), "sk-key", "gpt-4o")
        assert ok is True

    def test_unknown_model(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(404))
        ok, msg = _verify_model(_card("openai"), "sk-key", "gpt-nope")
        assert ok is False
        assert "Unknown" in msg


class TestVerifyModelGoogle:
    def test_success(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(200))
        ok, _ = _verify_model(_card("google"), "AIzaKey", "gemini-2.0-flash")
        assert ok is True

    def test_unknown_model(self, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(404))
        ok, msg = _verify_model(_card("google"), "AIzaKey", "gemini-nope")
        assert ok is False
        assert "Unknown" in msg


# ---------------------------------------------------------------------------
# _verify_model — Bedrock (api_key is the region)
# ---------------------------------------------------------------------------


class TestVerifyModelBedrock:
    def test_inference_profile_soft_accepted_without_api_call(self):
        # Leading us./eu./global. ids aren't in list_foundation_models — accept
        # once the region resolves. No boto3 needed, so no mock required.
        ok, _ = _verify_model(_card("bedrock"), "us-east-1", "us.anthropic.claude-sonnet-4-20250514-v1:0")
        assert ok is True

    def _inject_boto3(self, monkeypatch, model_summaries):
        """Inject a fake boto3 module (the real one is an optional extra)."""
        import sys
        import types

        class _Client:
            def list_foundation_models(self, **kw):
                return {"modelSummaries": model_summaries}

        class _Session:
            def __init__(self, *a, **kw):
                pass

            def client(self, *a, **kw):
                return _Client()

        fake = types.ModuleType("boto3")
        fake.Session = _Session
        monkeypatch.setitem(sys.modules, "boto3", fake)
        monkeypatch.setattr("scrum_agent.config.get_aws_profile", lambda: None)

    def test_plain_model_id_found_in_region(self, monkeypatch):
        self._inject_boto3(monkeypatch, [{"modelId": "anthropic.claude-3-sonnet"}])
        ok, _ = _verify_model(_card("bedrock"), "us-east-1", "anthropic.claude-3-sonnet")
        assert ok is True

    def test_plain_model_id_missing_in_region(self, monkeypatch):
        self._inject_boto3(monkeypatch, [])
        ok, msg = _verify_model(_card("bedrock"), "us-east-1", "anthropic.claude-3-sonnet")
        assert ok is False
        assert "not available" in msg.lower()


class TestVerifyModelUnknownProvider:
    def test_unknown_provider_returns_false(self):
        ok, msg = _verify_model({"provider_val": "mystery"}, "key", "some-model")
        assert ok is False
        assert "Unknown provider" in msg


# ---------------------------------------------------------------------------
# Screen builders
# ---------------------------------------------------------------------------


class TestModelSelectScreen:
    def test_returns_panel(self):
        panel = _build_model_select_screen(_card("anthropic"), ["claude-opus-4-8", "Custom…"], 0)
        assert isinstance(panel, Panel)

    def test_single_entry(self):
        panel = _build_model_select_screen(_card("openai"), ["Custom…"], 0)
        assert isinstance(panel, Panel)

    def test_long_model_id_renders(self):
        entries = ["us.anthropic.claude-sonnet-4-20250514-v1:0", "Custom…"]
        out = _render(_build_model_select_screen(_card("bedrock"), entries, 0))
        # The id is long enough it may wrap/crop; a distinctive fragment survives.
        assert "claude-sonnet-4" in out

    def test_error_line_shown(self):
        out = _render(_build_model_select_screen(_card("openai"), ["gpt-4o", "Custom…"], 0, error="Unknown model"))
        assert "Unknown model" in out


class TestModelInputScreen:
    def test_returns_panel(self):
        assert isinstance(_build_model_input_screen(_card("anthropic"), ""), Panel)

    def test_value_is_plaintext_not_masked(self):
        # Model ids are not secrets — the typed value must render as-is, no bullets.
        out = _render(_build_model_input_screen(_card("anthropic"), "claude-opus-4-8"))
        assert "claude-opus-4-8" in out
        assert "•" not in out

    def test_verified_state(self):
        assert isinstance(_build_model_input_screen(_card("openai"), "gpt-4o", verified=True), Panel)

    def test_error_state(self):
        out = _render(_build_model_input_screen(_card("openai"), "gpt-nope", verified=False, error="Unknown model"))
        assert "Unknown model" in out

    def test_verifying_state(self):
        panel = _build_model_input_screen(
            _card("google"), "gemini-2.0-flash", verifying=True, border_override="rgb(1,1,1)"
        )
        assert isinstance(panel, Panel)


# ---------------------------------------------------------------------------
# Data integrity — preset defaults must match _PROVIDER_DEFAULTS
# ---------------------------------------------------------------------------


class TestModelDataIntegrity:
    @pytest.mark.parametrize("card", _PROVIDER_CARDS, ids=lambda c: c["provider_val"])
    def test_default_matches_provider_defaults(self, card):
        default = card["models"]["default"]
        assert default == _PROVIDER_DEFAULTS[card["provider_val"]]
        # The default is always offered as a preset the user can pick.
        assert default in card["models"]["presets"]


# ---------------------------------------------------------------------------
# Wizard propagation — LLM_MODEL is written when select_provider returns it
# ---------------------------------------------------------------------------


class TestWizardModelPropagation:
    def _patch_config_file(self, monkeypatch, tmp_path):
        config_file = tmp_path / ".env"
        monkeypatch.setattr("scrum_agent.setup_wizard.get_config_file", lambda: config_file)
        monkeypatch.setattr("scrum_agent.config.get_config_file", lambda: config_file)
        return config_file

    def test_llm_model_written_to_env(self, monkeypatch, tmp_path):
        config_file = self._patch_config_file(monkeypatch, tmp_path)
        result = dict(_PROVIDERS["1"])
        result["api_key"] = "sk-ant-key"
        result["llm_model"] = "claude-opus-4-8"
        monkeypatch.setattr("scrum_agent.setup_wizard.select_provider", lambda *a, **kw: result)
        console = Console(file=StringIO(), highlight=False)
        run_setup_wizard(console)
        content = config_file.read_text()
        assert "LLM_MODEL=claude-opus-4-8" in content

    def test_no_llm_model_leaves_env_unset(self, monkeypatch, tmp_path):
        config_file = self._patch_config_file(monkeypatch, tmp_path)
        result = dict(_PROVIDERS["1"])
        result["api_key"] = "sk-ant-key"  # no llm_model key
        monkeypatch.setattr("scrum_agent.setup_wizard.select_provider", lambda *a, **kw: result)
        console = Console(file=StringIO(), highlight=False)
        run_setup_wizard(console)
        content = config_file.read_text()
        assert "LLM_MODEL" not in content
