"""The five context MCP tools, driven through the real FastMCP app."""

from __future__ import annotations

import json
from datetime import date

import anyio
import pytest

pytest.importorskip("mcp")

from mcp.shared.memory import create_connected_server_and_client_session  # noqa: E402

from yeaboi.mcp.server import create_app  # noqa: E402


def call_tool(name: str, arguments: dict | None = None) -> dict:
    async def _run():
        app = create_app()
        async with create_connected_server_and_client_session(app._mcp_server) as client:
            result = await client.call_tool(name, arguments or {})
            return json.loads(result.content[0].text)

    return anyio.run(_run)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db = tmp_path / "sessions.db"
    monkeypatch.setattr("yeaboi.paths.get_db_path", lambda: db)
    monkeypatch.delenv("YEABOI_CONTEXT_STANDUP", raising=False)
    monkeypatch.setattr("yeaboi.context.window._from_tracker", lambda: None)
    return db


@pytest.fixture
def seeded(tmp_db):
    from yeaboi.agent.state import StandupReport
    from yeaboi.context.labels import LabelStore
    from yeaboi.standup.store import StandupStore

    with StandupStore(tmp_db) as store:
        run = store.record_run(StandupReport(session_id="p1", date=date.today().isoformat()))
    with LabelStore(tmp_db) as labels:
        labels.set_labels("standup", "p1", str(run), project="Apollo", tags=["q3"])
    return str(run)


class TestContextTools:
    def test_options(self, seeded):
        payload = call_tool("context_options", {"mode": "standup"})
        assert payload["ok"] is True, payload
        data = payload["data"]
        assert data["projects"] == ["Apollo"] and "mode:standup" in data["defaults"]["tags"]
        assert next(row for row in data["sources"] if row["key"] == "standup")["count"] == 1

    def test_options_unknown_mode_is_an_error_envelope(self, tmp_db):
        payload = call_tool("context_options", {"mode": "stanup"})
        assert payload["ok"] is False and "unknown mode" in payload["error"]["message"]

    def test_preview_spec_and_object(self, seeded):
        payload = call_tool("context_preview", {"context": "standup@month", "rows": True})
        assert payload["ok"] is True, payload
        assert (
            payload["data"]["counts"]["standup"] == 1 and payload["data"]["rows"]["standup"][0]["project"] == "Apollo"
        )
        as_object = call_tool("context_preview", {"context": {"sources": ["standup"], "window": {"kind": "month"}}})
        assert as_object["data"]["counts"]["standup"] == 1

    def test_preview_typo_is_an_error_envelope(self, tmp_db):
        payload = call_tool("context_preview", {"context": "stanup"})
        assert payload["ok"] is False and "standup" in payload["error"]["message"]

    def test_labels_set_get_list(self, seeded):
        payload = call_tool(
            "session_labels_set",
            {"mode": "standup", "session_id": "p1", "run_id": seeded, "project_label": "Zeus", "tags": ["Q4"]},
        )
        assert payload["ok"] is True, payload
        assert payload["data"]["project_label"] == "Zeus" and payload["data"]["tags"] == ["q3", "q4"]
        got = call_tool("session_labels_get", {"mode": "standup", "session_id": "p1", "run_id": seeded})
        assert got["data"] == payload["data"]
        listed = call_tool("session_labels_list", {"mode": "standup", "project_label": "Zeus", "tags": ["q4"]})
        assert [row["run_id"] for row in listed["data"]["labels"]] == [seeded]

    def test_labels_get_missing_is_an_error_envelope(self, tmp_db):
        payload = call_tool("session_labels_get", {"mode": "retro", "session_id": "p9"})
        assert payload["ok"] is False and "no labels" in payload["error"]["message"]

    def test_labels_set_without_a_label_keeps_it(self, seeded):
        ids = {"mode": "standup", "session_id": "p1", "run_id": "1"}
        call_tool("session_labels_set", {**ids, "project_label": "Apollo"})
        kept = call_tool("session_labels_set", {**ids, "tags": ["x"]})
        assert kept["data"]["project_label"] == "Apollo"
        cleared = call_tool("session_labels_set", {**ids, "project_label": ""})
        assert cleared["data"]["project_label"] == ""

    def test_labels_set_unknown_mode_is_an_error_envelope(self, tmp_db):
        payload = call_tool("session_labels_set", {"mode": "nope", "session_id": "p1"})
        assert payload["ok"] is False
