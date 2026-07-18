"""Tests for the LLM instance factory."""

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel

from yeaboi.agent.llm import (
    _PROVIDER_DEFAULTS,
    DEFAULT_MODEL,
    build_multimodal_content,
    get_llm,
    get_usage_stats,
    invoke_with_images,
    load_image_b64,
    reset_usage_stats,
    track_usage,
)


class TestGetLlmAnthropic:
    """Tests for the default Anthropic provider."""

    def test_returns_base_chat_model(self, monkeypatch):
        """get_llm() must return a BaseChatModel regardless of provider."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        llm = get_llm()
        assert isinstance(llm, BaseChatModel)

    def test_default_provider_is_anthropic(self, monkeypatch):
        """Without LLM_PROVIDER set, the result must be a ChatAnthropic instance."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        llm = get_llm()
        assert isinstance(llm, ChatAnthropic)

    def test_explicit_anthropic_provider(self, monkeypatch):
        """LLM_PROVIDER=anthropic must return ChatAnthropic."""
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        llm = get_llm()
        assert isinstance(llm, ChatAnthropic)

    def test_default_model(self, monkeypatch):
        """Anthropic default model must be the claude-sonnet identifier."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        llm = get_llm()
        assert llm.model == DEFAULT_MODEL
        assert llm.model == "claude-sonnet-4-6"

    def test_default_temperature(self, monkeypatch):
        """Default temperature must be 0.0 for deterministic output."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        llm = get_llm()
        assert llm.temperature == 0.0

    def test_model_arg_overrides_default(self, monkeypatch):
        """Passing model= explicitly must override the provider default."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        llm = get_llm(model="claude-haiku-4-5-20251001")
        assert llm.model == "claude-haiku-4-5-20251001"

    def test_custom_temperature(self, monkeypatch):
        """Custom temperature must be forwarded to the chat model."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        llm = get_llm(temperature=0.7)
        assert llm.temperature == 0.7

    def test_raises_when_anthropic_key_missing(self, monkeypatch):
        """Must raise OSError when LLM_PROVIDER=anthropic and ANTHROPIC_API_KEY is absent."""
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(OSError, match="ANTHROPIC_API_KEY is not set"):
            get_llm()

    def test_api_key_wired_from_env(self, monkeypatch):
        """The API key must be read from the environment and forwarded to ChatAnthropic."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        llm = get_llm()
        # ChatAnthropic stores the key as a SecretStr
        assert llm.anthropic_api_key.get_secret_value() == "sk-ant-test-key"


class TestGetLlmModelOverride:
    """Tests for LLM_MODEL env-var override (applies to all providers)."""

    def test_llm_model_env_overrides_default(self, monkeypatch):
        """LLM_MODEL env var must override the provider's default model."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.setenv("LLM_MODEL", "claude-opus-4-6")
        llm = get_llm()
        assert llm.model == "claude-opus-4-6"

    def test_model_arg_takes_priority_over_llm_model_env(self, monkeypatch):
        """The model= argument must take priority over the LLM_MODEL env var."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.setenv("LLM_MODEL", "claude-opus-4-6")
        llm = get_llm(model="claude-haiku-4-5-20251001")
        assert llm.model == "claude-haiku-4-5-20251001"


class TestGetLlmOpenAI:
    """Tests for the OpenAI provider."""

    def test_openai_provider_returns_chat_openai(self, monkeypatch):
        """LLM_PROVIDER=openai must return a ChatOpenAI instance."""
        pytest.importorskip("langchain_openai", reason="langchain-openai not installed")
        from langchain_openai import ChatOpenAI

        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")
        monkeypatch.delenv("LLM_MODEL", raising=False)
        llm = get_llm()
        assert isinstance(llm, ChatOpenAI)

    def test_openai_default_model(self, monkeypatch):
        """OpenAI provider default model must be gpt-4o."""
        pytest.importorskip("langchain_openai", reason="langchain-openai not installed")
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")
        monkeypatch.delenv("LLM_MODEL", raising=False)
        llm = get_llm()
        assert llm.model_name == _PROVIDER_DEFAULTS["openai"]

    def test_openai_raises_when_key_missing(self, monkeypatch):
        """Must raise OSError when LLM_PROVIDER=openai and OPENAI_API_KEY is absent."""
        pytest.importorskip("langchain_openai", reason="langchain-openai not installed")
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(OSError, match="OPENAI_API_KEY is not set"):
            get_llm()

    def test_openai_missing_package_raises_import_error(self, monkeypatch):
        """Must raise ImportError with install instructions if langchain-openai is absent."""
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "langchain_openai":
                raise ImportError("No module named 'langchain_openai'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        with pytest.raises(ImportError, match="langchain-openai is not installed"):
            get_llm()


class TestGetLlmGoogle:
    """Tests for the Google Gemini provider."""

    def test_google_provider_returns_chat_google(self, monkeypatch):
        """LLM_PROVIDER=google must return a ChatGoogleGenerativeAI instance."""
        pytest.importorskip("langchain_google_genai", reason="langchain-google-genai not installed")
        from langchain_google_genai import ChatGoogleGenerativeAI

        monkeypatch.setenv("LLM_PROVIDER", "google")
        monkeypatch.setenv("GOOGLE_API_KEY", "google-test-key")
        monkeypatch.delenv("LLM_MODEL", raising=False)
        llm = get_llm()
        assert isinstance(llm, ChatGoogleGenerativeAI)

    def test_google_raises_when_key_missing(self, monkeypatch):
        """Must raise OSError when LLM_PROVIDER=google and GOOGLE_API_KEY is absent."""
        pytest.importorskip("langchain_google_genai", reason="langchain-google-genai not installed")
        monkeypatch.setenv("LLM_PROVIDER", "google")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        with pytest.raises(OSError, match="GOOGLE_API_KEY is not set"):
            get_llm()

    def test_google_missing_package_raises_import_error(self, monkeypatch):
        """Must raise ImportError with install instructions if langchain-google-genai is absent."""
        monkeypatch.setenv("LLM_PROVIDER", "google")
        monkeypatch.setenv("GOOGLE_API_KEY", "google-test")
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "langchain_google_genai":
                raise ImportError("No module named 'langchain_google_genai'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        with pytest.raises(ImportError, match="langchain-google-genai is not installed"):
            get_llm()


class TestGetLlmUnknownProvider:
    """Tests for unknown/unsupported provider values."""

    def test_unknown_provider_raises_value_error(self, monkeypatch):
        """An unrecognised LLM_PROVIDER must raise ValueError with clear guidance."""
        monkeypatch.setenv("LLM_PROVIDER", "mistral")
        with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
            get_llm()

    def test_error_message_lists_valid_providers(self, monkeypatch):
        """The ValueError message must name the valid providers."""
        monkeypatch.setenv("LLM_PROVIDER", "llama")
        with pytest.raises(ValueError, match="anthropic.*openai.*google"):
            get_llm()


class TestProviderDefaults:
    """Tests for the _PROVIDER_DEFAULTS constant."""

    def test_anthropic_default_is_sonnet(self):
        assert _PROVIDER_DEFAULTS["anthropic"] == "claude-sonnet-4-6"

    def test_openai_default_is_gpt4o(self):
        assert _PROVIDER_DEFAULTS["openai"] == "gpt-4o"

    def test_google_default_is_gemini_flash(self):
        assert _PROVIDER_DEFAULTS["google"] == "gemini-2.5-flash"

    def test_default_model_constant_matches_anthropic(self):
        """DEFAULT_MODEL backward-compat constant must equal the Anthropic default."""
        assert DEFAULT_MODEL == _PROVIDER_DEFAULTS["anthropic"]


class TestTrackUsage:
    """Tests for token usage tracking."""

    def setup_method(self):
        """Reset usage stats before each test to avoid pollution."""
        reset_usage_stats()

    def test_anthropic_style_response(self):
        """track_usage with Anthropic-style response (response_metadata.usage.input_tokens/output_tokens)."""
        from types import SimpleNamespace

        resp = SimpleNamespace(response_metadata={"usage": {"input_tokens": 100, "output_tokens": 50}})
        track_usage(resp)
        stats = get_usage_stats()
        assert stats["input_tokens"] == 100
        assert stats["output_tokens"] == 50
        assert stats["total_tokens"] == 150
        assert stats["call_count"] == 1

    def test_openai_style_response(self):
        """track_usage with OpenAI-style response (response_metadata.token_usage.prompt_tokens/completion_tokens)."""
        from types import SimpleNamespace

        resp = SimpleNamespace(response_metadata={"token_usage": {"prompt_tokens": 200, "completion_tokens": 80}})
        track_usage(resp)
        stats = get_usage_stats()
        assert stats["input_tokens"] == 200
        assert stats["output_tokens"] == 80
        assert stats["total_tokens"] == 280
        assert stats["call_count"] == 1

    def test_accumulates_across_multiple_calls(self):
        """track_usage accumulates across multiple calls."""
        from types import SimpleNamespace

        resp1 = SimpleNamespace(response_metadata={"usage": {"input_tokens": 100, "output_tokens": 50}})
        resp2 = SimpleNamespace(response_metadata={"usage": {"input_tokens": 200, "output_tokens": 75}})
        track_usage(resp1)
        track_usage(resp2)
        stats = get_usage_stats()
        assert stats["input_tokens"] == 300
        assert stats["output_tokens"] == 125
        assert stats["total_tokens"] == 425
        assert stats["call_count"] == 2

    def test_empty_metadata_logs_warning(self, caplog):
        """track_usage with empty metadata logs warning."""
        import logging
        from types import SimpleNamespace

        resp = SimpleNamespace(response_metadata={})
        with caplog.at_level(logging.WARNING, logger="yeaboi.agent.llm"):
            track_usage(resp)
        assert "no token data found" in caplog.text
        stats = get_usage_stats()
        assert stats["call_count"] == 0

    def test_get_usage_stats_returns_accumulated_totals(self):
        """get_usage_stats returns accumulated totals."""
        from types import SimpleNamespace

        resp = SimpleNamespace(response_metadata={"usage": {"input_tokens": 500, "output_tokens": 200}})
        track_usage(resp)
        stats = get_usage_stats()
        assert stats["input_tokens"] == 500
        assert stats["output_tokens"] == 200
        assert stats["total_tokens"] == 700
        assert stats["call_count"] == 1

    def test_get_usage_stats_returns_copy_not_reference(self):
        """get_usage_stats returns copy not reference."""
        stats = get_usage_stats()
        stats["input_tokens"] = 999999
        fresh = get_usage_stats()
        assert fresh["input_tokens"] != 999999

    def test_reset_usage_stats_clears_counters(self):
        """reset_usage_stats clears counters."""
        from types import SimpleNamespace

        resp = SimpleNamespace(response_metadata={"usage": {"input_tokens": 100, "output_tokens": 50}})
        track_usage(resp)
        assert get_usage_stats()["total_tokens"] > 0
        reset_usage_stats()
        stats = get_usage_stats()
        assert stats["input_tokens"] == 0
        assert stats["output_tokens"] == 0
        assert stats["total_tokens"] == 0
        assert stats["call_count"] == 0


class TestMultimodalHelpers:
    """Tests for the pasted-screenshot (vision) helpers."""

    PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

    @pytest.fixture
    def png_file(self, tmp_path):
        p = tmp_path / "shot.png"
        p.write_bytes(self.PNG_BYTES)
        return p

    def test_load_image_b64_happy_path(self, png_file):
        import base64

        loaded = load_image_b64(png_file)
        assert loaded is not None
        b64, mime = loaded
        assert mime == "image/png"
        assert base64.b64decode(b64) == self.PNG_BYTES

    def test_load_image_b64_jpeg_mime(self, tmp_path):
        p = tmp_path / "shot.jpg"
        p.write_bytes(b"\xff\xd8\xff")
        assert load_image_b64(p)[1] == "image/jpeg"

    def test_load_image_b64_missing_file_returns_none(self, tmp_path):
        assert load_image_b64(tmp_path / "gone.png") is None

    def test_build_content_no_images_returns_plain_string(self):
        assert build_multimodal_content("hello", []) == "hello"
        assert build_multimodal_content("hello", None) == "hello"

    def test_build_content_with_image_returns_blocks(self, png_file):
        content = build_multimodal_content("describe this", [str(png_file)])
        assert isinstance(content, list)
        assert content[0] == {"type": "text", "text": "describe this"}
        img = content[1]
        assert img["type"] == "image"
        assert img["source_type"] == "base64"
        assert img["mime_type"] == "image/png"
        assert img["data"]

    def test_build_content_all_missing_degrades_to_string(self, tmp_path):
        content = build_multimodal_content("text", [str(tmp_path / "gone.png")])
        assert content == "text"


class TestInvokeWithImages:
    """invoke_with_images must be a drop-in for invoke([HumanMessage(prompt)])."""

    class _FakeLLM:
        def __init__(self, fail_first=False):
            self.fail_first = fail_first
            self.calls = []

        def invoke(self, messages):
            self.calls.append(messages)
            if self.fail_first and len(self.calls) == 1:
                raise ValueError("model does not support image input")
            return "response"

    def test_no_images_single_plain_invoke(self):
        llm = self._FakeLLM()
        assert invoke_with_images(llm, "prompt", []) == "response"
        assert len(llm.calls) == 1
        assert llm.calls[0][0].content == "prompt"

    def test_images_sent_as_blocks(self, tmp_path):
        p = tmp_path / "a.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        llm = self._FakeLLM()
        invoke_with_images(llm, "prompt", [str(p)])
        content = llm.calls[0][0].content
        assert isinstance(content, list)
        assert {b["type"] for b in content} == {"text", "image"}

    def test_rejected_images_retries_text_only(self, tmp_path):
        p = tmp_path / "a.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        llm = self._FakeLLM(fail_first=True)
        assert invoke_with_images(llm, "prompt", [str(p)]) == "response"
        assert len(llm.calls) == 2
        assert llm.calls[1][0].content == "prompt"  # retry dropped the image

    def test_text_only_failure_propagates(self):
        # With no images there is no retry — errors reach the caller's own
        # auth/billing handling untouched.
        llm = self._FakeLLM(fail_first=True)
        with pytest.raises(ValueError):
            invoke_with_images(llm, "prompt", [])
