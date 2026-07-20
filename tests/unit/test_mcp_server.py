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
    "plan_generate",
    "intake_questions",
    "plan_get",
    "plan_export",
    "plan_publish",
    "sessions_list",
    "session_get",
    "standup_run",
    "standup_history",
    "standup_config_get",
    "standup_config_set",
    "report_delivery",
    "perf_roster",
    "perf_one_on_one_prep",
    "perf_one_on_one_complete",
    "perf_six_month_review",
    "perf_note_add",
    "retro_history",
    "team_profile_get",
    "team_compare_plan_to_actuals",
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


@pytest.fixture
def provider_mode(monkeypatch):
    """Pin the LLM mode to 'provider' so engine-tool tests are deterministic."""
    monkeypatch.setenv("YEABOI_MCP_LLM", "provider")
    monkeypatch.setattr("yeaboi.config.is_llm_configured", lambda: (True, "ok"))


class TestEngineTools:
    """The LLM-backed tools with their engines monkeypatched (no real LLM/tracker calls)."""

    def test_plan_generate(self, seeded_session, provider_mode, monkeypatch):
        from yeaboi.sessions import SessionStore

        def fake_pipeline(questionnaire, *, on_progress=None, **kwargs):
            assert questionnaire.answers[1] == "A todo app"
            assert questionnaire.answers[6] == "4"
            assert questionnaire.answers[11] == "Python"  # explicit answer won
            if on_progress:
                on_progress("project_analyzer", 0)
            from yeaboi.paths import get_db_path

            with SessionStore(get_db_path()) as store:
                state = store.load_state("new-abcd1234-2026-07-20")
            state["_session_id"] = "new-abcd1234-2026-07-20"
            return state

        monkeypatch.setattr("yeaboi.agent.headless.run_planning_pipeline", fake_pipeline)
        payload = call_tool(
            "plan_generate",
            {"description": "A todo app", "team_size": 4, "answers": {"11": "Python"}},
        )
        assert payload["ok"] is True
        assert payload["llm_mode"] == "provider"
        assert payload["data"]["session_id"] == "new-abcd1234-2026-07-20"
        assert payload["data"]["stories"]

    def test_plan_generate_requires_description(self, tmp_db, provider_mode):
        payload = call_tool("plan_generate", {"description": "   "})
        assert payload["ok"] is False
        assert "description is required" in payload["error"]["message"]

    def test_plan_generate_rejects_bad_answer_keys(self, tmp_db, provider_mode):
        payload = call_tool("plan_generate", {"description": "An app", "answers": {"55": "x"}})
        assert payload["ok"] is False
        assert "question numbers 1-30" in payload["error"]["message"]

    def test_standup_run_defaults_no_delivery(self, seeded_session, provider_mode, monkeypatch):
        captured: dict = {}

        def fake_run_standup(session_id, *, deliver, days=None, **kwargs):
            captured.update(session_id=session_id, deliver=deliver, days=days)
            return {"team_summary": "all good", "warnings": ["Jira skipped"]}

        monkeypatch.setattr("yeaboi.standup.engine.run_standup", fake_run_standup)
        payload = call_tool("standup_run")
        assert payload["ok"] is True
        assert captured == {"session_id": seeded_session, "deliver": False, "days": None}
        assert payload["warnings"] == ["Jira skipped"]

    def test_report_delivery_validates_period(self, tmp_db, provider_mode):
        payload = call_tool("report_delivery", {"period": "fortnight"})
        assert payload["ok"] is False
        assert "period must be one of" in payload["error"]["message"]

    def test_report_delivery(self, tmp_db, provider_mode, monkeypatch):
        def fake_report(period, **kwargs):
            assert period == "last_sprint"
            return {"executive_summary": "shipped", "warnings": []}

        monkeypatch.setattr("yeaboi.reporting.engine.run_delivery_report", fake_report)
        payload = call_tool("report_delivery", {"period": "last_sprint"})
        assert payload["ok"] is True
        assert payload["data"]["executive_summary"] == "shipped"

    def test_perf_roster(self, tmp_db, monkeypatch):
        monkeypatch.setattr("yeaboi.performance.roster.fetch_roster", lambda **kw: [{"name": "Sam"}])
        payload = call_tool("perf_roster")
        assert payload["ok"] is True
        assert payload["data"]["engineers"] == [{"name": "Sam"}]

    def test_perf_one_on_one_prep(self, tmp_db, provider_mode, monkeypatch):
        monkeypatch.setattr(
            "yeaboi.performance.engine.run_one_on_one_prep",
            lambda engineer, **kw: {"engineer": engineer, "talking_points": ["velocity"], "warnings": []},
        )
        payload = call_tool("perf_one_on_one_prep", {"engineer": "Sam"})
        assert payload["ok"] is True
        assert payload["data"]["engineer"] == "Sam"

    def test_perf_one_on_one_complete_requires_transcript(self, tmp_db, provider_mode):
        payload = call_tool("perf_one_on_one_complete", {"engineer": "Sam", "transcript": " "})
        assert payload["ok"] is False
        assert "transcript is required" in payload["error"]["message"]

    def test_perf_one_on_one_complete_defaults_no_delivery(self, tmp_db, provider_mode, monkeypatch):
        captured: dict = {}

        def fake_complete(engineer, transcript, *, deliver, recipients=None, **kwargs):
            captured.update(engineer=engineer, deliver=deliver)
            return {"summary": "done", "warnings": []}

        monkeypatch.setattr("yeaboi.performance.engine.complete_one_on_one", fake_complete)
        payload = call_tool("perf_one_on_one_complete", {"engineer": "Sam", "transcript": "we talked"})
        assert payload["ok"] is True
        assert captured == {"engineer": "Sam", "deliver": False}

    def test_perf_six_month_review(self, tmp_db, provider_mode, monkeypatch):
        monkeypatch.setattr(
            "yeaboi.performance.engine.run_six_month_review",
            lambda engineer, *, period_months, **kw: {"engineer": engineer, "months": period_months, "warnings": []},
        )
        payload = call_tool("perf_six_month_review", {"engineer": "Sam", "period_months": 12})
        assert payload["ok"] is True
        assert payload["data"]["months"] == 12

    def test_standup_run_channels_passthrough(self, seeded_session, provider_mode, monkeypatch):
        captured: dict = {}

        def fake_run_standup(session_id, *, deliver, days=None, channels=None, **kwargs):
            captured.update(channels=channels)
            return {"team_summary": "ok", "warnings": []}

        monkeypatch.setattr("yeaboi.standup.engine.run_standup", fake_run_standup)
        payload = call_tool("standup_run", {"channels": ["slack", "email"]})
        assert payload["ok"] is True
        assert captured["channels"] == ["slack", "email"]

    def test_standup_run_rejects_bad_channel(self, seeded_session, provider_mode):
        payload = call_tool("standup_run", {"channels": ["pager"]})
        assert payload["ok"] is False
        assert "unknown delivery channel" in payload["error"]["message"]

    def test_report_delivery_window_passthrough(self, tmp_db, provider_mode, monkeypatch):
        captured: dict = {}

        def fake_report(period, **kwargs):
            captured.update(kwargs)
            return {"executive_summary": "q3", "warnings": []}

        monkeypatch.setattr("yeaboi.reporting.engine.run_delivery_report", fake_report)
        payload = call_tool(
            "report_delivery",
            {
                "period": "quarter",
                "window_start": "2026-04-01",
                "window_end": "2026-06-30",
                "sprint_names": ["Sprint 7", "Sprint 8"],
                "period_label_override": "Q2 2026",
            },
        )
        assert payload["ok"] is True
        assert captured["window_start"] == "2026-04-01"
        assert captured["window_end"] == "2026-06-30"
        assert captured["sprint_names"] == ("Sprint 7", "Sprint 8")
        assert captured["period_label_override"] == "Q2 2026"

    def test_perf_one_on_one_complete_images_passthrough(self, tmp_db, provider_mode, monkeypatch):
        captured: dict = {}

        def fake_complete(engineer, transcript, *, images=(), **kwargs):
            captured.update(images=images)
            return {"summary": "done", "warnings": []}

        monkeypatch.setattr("yeaboi.performance.engine.complete_one_on_one", fake_complete)
        payload = call_tool(
            "perf_one_on_one_complete",
            {"engineer": "Sam", "transcript": "notes", "images": ["/tmp/board.png"]},
        )
        assert payload["ok"] is True
        assert captured["images"] == ("/tmp/board.png",)

    def test_team_compare_plan_to_actuals(self, tmp_db, monkeypatch):
        from types import SimpleNamespace

        from yeaboi.tools import team_learning

        monkeypatch.setattr(
            team_learning,
            "compare_plan_to_actuals",
            SimpleNamespace(invoke=lambda args: '{"accuracy_pct": 82}'),
        )
        payload = call_tool("team_compare_plan_to_actuals")
        assert payload["ok"] is True
        assert payload["data"]["accuracy_pct"] == 82


class TestPlanPublish:
    def test_publish_success(self, seeded_session, monkeypatch):
        from yeaboi.export_targets import PublishResult

        captured: dict = {}

        def fake_publish(destination, *, title, markdown):
            captured.update(destination=destination, title=title)
            assert markdown  # a real markdown document was built
            return PublishResult(ok=True, message="Published", url="https://notion.so/x")

        monkeypatch.setattr("yeaboi.export_targets.publish_markdown", fake_publish)
        payload = call_tool("plan_publish", {"destination": "notion"})
        assert payload["ok"] is True
        assert payload["data"]["url"] == "https://notion.so/x"
        assert captured["destination"] == "notion"
        assert captured["title"].startswith("Sprint Plan")

    def test_publish_failure_surfaces_message(self, seeded_session, monkeypatch):
        from yeaboi.export_targets import PublishResult

        monkeypatch.setattr(
            "yeaboi.export_targets.publish_markdown",
            lambda destination, *, title, markdown: PublishResult(ok=False, message="Notion not configured"),
        )
        payload = call_tool("plan_publish", {"destination": "notion"})
        assert payload["ok"] is False
        assert "Notion not configured" in payload["error"]["message"]

    def test_publish_bad_destination(self, seeded_session):
        payload = call_tool("plan_publish", {"destination": "sharepoint"})
        assert payload["ok"] is False
        assert "Unsupported destination" in payload["error"]["message"]


class TestPerfNotes:
    def test_note_add_and_visible_to_store(self, tmp_db):
        payload = call_tool("perf_note_add", {"engineer": "Sam", "note_text": "great incident response"})
        assert payload["ok"] is True
        assert payload["data"]["note_id"] > 0

        from yeaboi.performance.store import PerformanceStore

        with PerformanceStore(tmp_db) as store:
            notes = store.get_notes("Sam")
        assert notes[0]["note_text"] == "great incident response"

    def test_note_add_requires_text(self, tmp_db):
        payload = call_tool("perf_note_add", {"engineer": "Sam", "note_text": "  "})
        assert payload["ok"] is False
        assert "note_text is required" in payload["error"]["message"]


class TestStandupConfigTools:
    def test_config_get_unset(self, seeded_session):
        payload = call_tool("standup_config_get")
        assert payload["ok"] is True
        assert payload["data"]["config"] is None
        assert "slack" in payload["data"]["valid_channels"]

    def test_config_set_creates_with_defaults(self, seeded_session):
        payload = call_tool("standup_config_set", {"time": "09:15", "delivery_channels": ["slack"]})
        assert payload["ok"] is True
        config = payload["data"]["config"]
        assert config["time"] == "09:15"
        assert config["delivery_channels"] == ["slack"]
        assert config["weekdays"] == "1-5"  # default kept
        assert config["enabled"] is False  # not enabled unless asked

    def test_config_set_merges_over_existing(self, seeded_session):
        call_tool("standup_config_set", {"time": "09:15", "delivery_channels": ["slack"]})
        payload = call_tool("standup_config_set", {"enabled": True})
        config = payload["data"]["config"]
        assert config["enabled"] is True
        assert config["time"] == "09:15"  # earlier value preserved
        assert config["delivery_channels"] == ["slack"]

    def test_config_set_rejects_bad_time(self, seeded_session):
        payload = call_tool("standup_config_set", {"time": "quarter past nine"})
        assert payload["ok"] is False
        assert "HH:MM" in payload["error"]["message"]

    def test_config_set_rejects_bad_channel(self, seeded_session):
        payload = call_tool("standup_config_set", {"delivery_channels": ["pager"]})
        assert payload["ok"] is False
        assert "unknown delivery channel" in payload["error"]["message"]


class TestServerEntry:
    def test_import_without_mcp_is_safe(self):
        # The package must import fine even where the extra is missing —
        # server.py defers the mcp import into create_app()/main().
        import yeaboi.mcp
        import yeaboi.mcp.server  # noqa: F401

        assert hasattr(yeaboi.mcp.server, "main")
