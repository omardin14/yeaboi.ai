"""Tests for the MCP server core (yeaboi.mcp.server + runtime + deterministic tools)."""

import json

import anyio
import pytest

from tests._node_helpers import (
    make_completed_questionnaire,
    make_dummy_analysis,
    make_sample_features,
    make_sample_sprints,
    make_sample_stories,
)

pytest.importorskip("mcp", reason="mcp extra not installed")

from mcp.shared.memory import create_connected_server_and_client_session  # noqa: E402

from yeaboi.mcp.runtime import LLM_HINT, envelope, error_envelope, to_jsonable  # noqa: E402
from yeaboi.mcp.server import create_app  # noqa: E402

EXPECTED_TOOLS = {
    "intake_questions",
    "plan_get",
    "plan_export",
    "sessions_list",
    "session_get",
    "standup_history",
    "retro_history",
    "team_profile_get",
}


def call_tool(name: str, arguments: dict | None = None) -> dict:
    """Drive the real FastMCP app through the SDK's in-memory transport."""

    async def _run():
        app = create_app()
        async with create_connected_server_and_client_session(app._mcp_server) as client:
            result = await client.call_tool(name, arguments or {})
            return json.loads(result.content[0].text)

    return anyio.run(_run)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Redirect every store to a per-test sessions DB."""
    db = tmp_path / "sessions.db"
    monkeypatch.setattr("yeaboi.paths.get_db_path", lambda: db)
    return db


@pytest.fixture
def seeded_session(tmp_db):
    """A complete planning session saved through the real SessionStore."""
    from yeaboi.sessions import SessionStore

    state = {
        "questionnaire": make_completed_questionnaire(),
        "project_analysis": make_dummy_analysis(),
        "features": make_sample_features(),
        "stories": make_sample_stories(),
        "sprints": make_sample_sprints(),
    }
    with SessionStore(tmp_db) as store:
        store.create_session("new-abcd1234-2026-07-20")
        store.save_state("new-abcd1234-2026-07-20", state)
        store.update_project_name("new-abcd1234-2026-07-20", "Test Project")
    return "new-abcd1234-2026-07-20"


class TestEnvelope:
    def test_success_shape(self):
        result = envelope({"a": 1}, llm_mode="provider", warnings=["w"])
        assert result == {"ok": True, "llm_mode": "provider", "warnings": ["w"], "data": {"a": 1}}

    def test_error_shape(self):
        result = error_envelope(ValueError("nope"))
        assert result["ok"] is False
        assert result["error"] == {"type": "ValueError", "message": "nope"}
        assert "hint" not in result

    def test_auth_error_gets_hint(self):
        result = error_envelope(RuntimeError("Invalid API key provided"))
        assert result["hint"] == LLM_HINT

    def test_to_jsonable_flattens_dataclasses_and_tuples(self):
        analysis = make_dummy_analysis()
        data = to_jsonable(analysis)
        assert data["project_name"] == "Test Project"
        assert isinstance(data["goals"], list)
        json.dumps(data)  # fully serializable


class TestToolInventory:
    def test_all_tools_registered(self):
        async def _run():
            app = create_app()
            async with create_connected_server_and_client_session(app._mcp_server) as client:
                listed = await client.list_tools()
                return {tool.name for tool in listed.tools}

        assert anyio.run(_run) == EXPECTED_TOOLS

    def test_stdout_stays_clean(self, capsys, tmp_db):
        # stdio transport rule: stdout carries JSON-RPC, so tool calls must
        # never print to it (stderr is fine).
        call_tool("sessions_list")
        assert capsys.readouterr().out == ""


class TestSessionTools:
    def test_sessions_list_empty(self, tmp_db):
        payload = call_tool("sessions_list")
        assert payload["ok"] is True
        assert payload["data"] == []

    def test_sessions_list_seeded(self, seeded_session):
        payload = call_tool("sessions_list")
        assert payload["ok"] is True
        assert payload["data"][0]["session_id"] == seeded_session
        assert payload["data"][0]["project_name"] == "Test Project"
        assert "session_state_raw" not in payload["data"][0]

    def test_session_get_defaults_to_latest(self, seeded_session):
        payload = call_tool("session_get")
        assert payload["ok"] is True
        data = payload["data"]
        assert data["session_id"] == seeded_session
        assert data["artifacts"]["stories"] == len(make_sample_stories())
        assert data["artifacts"]["sprints"] == len(make_sample_sprints())
        assert data["questionnaire_completed"] is True

    def test_session_get_unknown_id_errors(self, tmp_db):
        payload = call_tool("session_get", {"session_id": "new-ffffffff-2026-01-01"})
        assert payload["ok"] is False
        assert payload["error"]["type"] == "ValueError"


class TestPlanningTools:
    def test_intake_questions_contract(self, tmp_db):
        payload = call_tool("intake_questions")
        assert payload["ok"] is True
        data = payload["data"]
        assert len(data["questions"]) == 30
        assert 6 in data["smart_essentials"]
        assert data["defaults"]  # non-empty
        assert data["choice_metadata"]["10"]["options"]  # Q10 is a choice question

    def test_plan_get_seeded(self, seeded_session):
        payload = call_tool("plan_get")
        assert payload["ok"] is True
        plan = payload["data"]
        assert plan["session_id"] == seeded_session
        assert plan["stories"]
        assert plan["sprints"]

    def test_plan_get_no_sessions_errors(self, tmp_db):
        payload = call_tool("plan_get")
        assert payload["ok"] is False
        assert "No saved sessions" in payload["error"]["message"]

    def test_plan_export_markdown(self, seeded_session, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # exporter writes relative to CWD
        payload = call_tool("plan_export", {"format": "markdown"})
        assert payload["ok"] is True
        from pathlib import Path

        assert Path(payload["data"]["path"]).exists()

    def test_plan_export_bad_format(self, seeded_session):
        payload = call_tool("plan_export", {"format": "pdf"})
        assert payload["ok"] is False
        assert "Unsupported format" in payload["error"]["message"]


class TestHistoryTools:
    def test_standup_history_empty(self, seeded_session):
        payload = call_tool("standup_history")
        assert payload["ok"] is True
        assert payload["data"]["history"] == []
        assert payload["data"]["latest_report"] is None

    def test_retro_history_empty(self, seeded_session):
        payload = call_tool("retro_history")
        assert payload["ok"] is True
        assert payload["data"]["history"] == []

    def test_team_profile_get_no_db(self, tmp_db):
        payload = call_tool("team_profile_get")
        assert payload["ok"] is True
        assert payload["data"]["profiles"] == []


class TestServerEntry:
    def test_import_without_mcp_is_safe(self):
        # The package must import fine even where the extra is missing —
        # server.py defers the mcp import into create_app()/main().
        import yeaboi.mcp
        import yeaboi.mcp.server  # noqa: F401

        assert hasattr(yeaboi.mcp.server, "main")
