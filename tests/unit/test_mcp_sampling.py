"""Tests for the MCP sampling bridge (yeaboi.mcp.sampling) and run_engine dispatch."""

from types import SimpleNamespace

import anyio
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

pytest.importorskip("mcp", reason="mcp extra not installed")

from yeaboi.mcp.runtime import run_engine  # noqa: E402
from yeaboi.mcp.sampling import (  # noqa: E402
    DEFAULT_MAX_TOKENS,
    SamplingChatModel,
    convert_messages,
    resolve_llm_mode,
)


class FakeSession:
    """Stub of mcp ServerSession: records create_message calls, answers capability checks."""

    def __init__(self, text: str = "sampled reply", sampling: bool = True):
        self.text = text
        self.sampling = sampling
        self.calls: list[dict] = []

    async def create_message(self, messages, *, max_tokens, system_prompt=None, **kwargs):
        self.calls.append({"messages": messages, "max_tokens": max_tokens, "system_prompt": system_prompt})
        return SimpleNamespace(content=SimpleNamespace(text=self.text), model="host-model")

    def check_client_capability(self, _caps) -> bool:
        return self.sampling


def make_ctx(sampling: bool = True) -> SimpleNamespace:
    return SimpleNamespace(session=FakeSession(sampling=sampling))


class TestConvertMessages:
    def test_system_becomes_system_prompt(self):
        sampling, system = convert_messages(
            [SystemMessage(content="be brief"), HumanMessage(content="hi"), AIMessage(content="hello")]
        )
        assert system == "be brief"
        assert [m.role for m in sampling] == ["user", "assistant"]
        assert sampling[0].content.text == "hi"

    def test_no_system_prompt_is_none(self):
        _, system = convert_messages([HumanMessage(content="hi")])
        assert system is None

    def test_multiple_system_messages_concatenate(self):
        _, system = convert_messages([SystemMessage(content="a"), SystemMessage(content="b")])
        assert system == "a\n\nb"

    def test_image_blocks_dropped_text_kept(self):
        message = HumanMessage(
            content=[
                {"type": "text", "text": "describe this"},
                {"type": "image", "source_type": "base64", "mime_type": "image/png", "data": "x"},
            ]
        )
        sampling, _ = convert_messages([message])
        assert sampling[0].content.text == "describe this"


class TestSamplingChatModel:
    def test_sync_invoke_from_worker_thread(self):
        # The real call path: engines run .invoke() on an anyio worker thread
        # and the model bridges back to the event loop for create_message.
        session = FakeSession(text="the plan")
        model = SamplingChatModel(session=session)

        async def main():
            return await anyio.to_thread.run_sync(
                lambda: model.invoke([SystemMessage(content="sys"), HumanMessage(content="plan it")])
            )

        result = anyio.run(main)
        assert result.content == "the plan"
        assert result.response_metadata["model"] == "host-model"
        assert session.calls[0]["system_prompt"] == "sys"
        assert session.calls[0]["max_tokens"] == DEFAULT_MAX_TOKENS

    def test_async_invoke(self):
        model = SamplingChatModel(session=FakeSession(text="async reply"))

        async def main():
            return await model.ainvoke([HumanMessage(content="hi")])

        assert anyio.run(main).content == "async reply"

    def test_max_tokens_env_override(self, monkeypatch):
        monkeypatch.setenv("YEABOI_MCP_MAX_TOKENS", "1234")
        session = FakeSession()
        model = SamplingChatModel(session=session)

        async def main():
            return await model.ainvoke([HumanMessage(content="hi")])

        anyio.run(main)
        assert session.calls[0]["max_tokens"] == 1234

    def test_invalid_max_tokens_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("YEABOI_MCP_MAX_TOKENS", "lots")
        session = FakeSession()
        model = SamplingChatModel(session=session)

        async def main():
            return await model.ainvoke([HumanMessage(content="hi")])

        anyio.run(main)
        assert session.calls[0]["max_tokens"] == DEFAULT_MAX_TOKENS


class TestResolveLlmMode:
    def test_sampling_when_client_supports_it(self, monkeypatch):
        monkeypatch.delenv("YEABOI_MCP_LLM", raising=False)
        assert resolve_llm_mode(make_ctx(sampling=True)) == "sampling"

    def test_provider_when_no_sampling_but_configured(self, monkeypatch):
        monkeypatch.delenv("YEABOI_MCP_LLM", raising=False)
        monkeypatch.setattr("yeaboi.config.is_llm_configured", lambda: (True, "ok"))
        assert resolve_llm_mode(make_ctx(sampling=False)) == "provider"

    def test_fallback_when_nothing_available(self, monkeypatch):
        monkeypatch.delenv("YEABOI_MCP_LLM", raising=False)
        monkeypatch.setattr("yeaboi.config.is_llm_configured", lambda: (False, "no key"))
        assert resolve_llm_mode(make_ctx(sampling=False)) == "fallback"

    def test_env_forces_provider_over_sampling(self, monkeypatch):
        monkeypatch.setenv("YEABOI_MCP_LLM", "provider")
        monkeypatch.setattr("yeaboi.config.is_llm_configured", lambda: (True, "ok"))
        assert resolve_llm_mode(make_ctx(sampling=True)) == "provider"

    def test_capability_check_error_falls_through(self, monkeypatch):
        monkeypatch.delenv("YEABOI_MCP_LLM", raising=False)
        monkeypatch.setattr("yeaboi.config.is_llm_configured", lambda: (False, "no"))
        ctx = SimpleNamespace(session=SimpleNamespace())  # no check_client_capability at all
        assert resolve_llm_mode(ctx) == "fallback"


class TestRunEngineSamplingInjection:
    def test_engine_sees_sampling_model_via_get_llm(self, monkeypatch):
        monkeypatch.delenv("YEABOI_MCP_LLM", raising=False)
        ctx = make_ctx(sampling=True)

        def fake_engine():
            # What every yeaboi engine does internally:
            from langchain_core.messages import HumanMessage

            from yeaboi.agent.llm import get_llm

            response = get_llm().invoke([HumanMessage(content="generate")])
            return {"summary": response.content, "warnings": []}

        payload = anyio.run(lambda: run_engine(ctx, fake_engine))
        assert payload["ok"] is True
        assert payload["llm_mode"] == "sampling"
        assert payload["data"]["summary"] == "sampled reply"

    def test_fallback_mode_adds_warning(self, monkeypatch):
        monkeypatch.delenv("YEABOI_MCP_LLM", raising=False)
        monkeypatch.setattr("yeaboi.config.is_llm_configured", lambda: (False, "no"))
        ctx = make_ctx(sampling=False)

        payload = anyio.run(lambda: run_engine(ctx, lambda: {"summary": "skeleton"}))
        assert payload["ok"] is True
        assert payload["llm_mode"] == "fallback"
        assert any("deterministic fallback" in w for w in payload["warnings"])

    def test_engine_exception_becomes_error_envelope(self, monkeypatch):
        monkeypatch.delenv("YEABOI_MCP_LLM", raising=False)
        ctx = make_ctx(sampling=True)

        def broken_engine():
            raise RuntimeError("invalid api key for provider")

        payload = anyio.run(lambda: run_engine(ctx, broken_engine))
        assert payload["ok"] is False
        assert payload["llm_mode"] == "sampling"
        assert "hint" in payload

    def test_result_warnings_surface_in_envelope(self):
        ctx = make_ctx(sampling=True)
        payload = anyio.run(lambda: run_engine(ctx, lambda: {"summary": "x", "warnings": ["Jira 401"]}))
        assert payload["warnings"] == ["Jira 401"]
