"""The /api/context and /api/sessions/{mode}/{id}/labels routes — socketless, over AppServer.handle()."""

from __future__ import annotations

import json
from datetime import date

import pytest

from yeaboi.app.router import parse_request
from yeaboi.app.server import AppServer

TOKEN = "test-token"
TODAY = date(2026, 9, 11)


@pytest.fixture
def app(tmp_path, monkeypatch):
    db = tmp_path / "sessions.db"
    monkeypatch.setattr("yeaboi.paths.get_db_path", lambda: db)
    monkeypatch.delenv("YEABOI_CONTEXT_STANDUP", raising=False)
    monkeypatch.setattr("yeaboi.context.window._from_tracker", lambda: None)
    server = AppServer(token=TOKEN)
    server.db = db
    return server


@pytest.fixture
def seeded(app):
    from yeaboi.agent.state import StandupReport
    from yeaboi.context.labels import LabelStore
    from yeaboi.standup.store import StandupStore

    with StandupStore(app.db) as store:
        run = store.record_run(StandupReport(session_id="p1", date=date.today().isoformat()))
    with LabelStore(app.db) as labels:
        labels.set_labels("standup", "p1", str(run), project="Apollo", tags=["q3"])
    return str(run)


def request(app: AppServer, method: str, path: str, payload: dict | None = None):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    body = json.dumps(payload).encode() if payload is not None else b""
    return app.handle(parse_request(method, path, headers, body))


class TestOptions:
    def test_serves_the_picker_payload(self, app, seeded):
        resp = request(app, "GET", "/api/context/options?mode=standup")
        assert resp.code == 200, resp.body
        payload = json.loads(resp.body)
        assert set(payload) == {"sources", "windows", "projects", "tags", "calendar", "default", "defaults"}
        assert next(row for row in payload["sources"] if row["key"] == "standup")["count"] == 1
        assert payload["projects"] == ["Apollo"] and {t["tag"] for t in payload["tags"]} == {"q3"}
        assert payload["default"] is None and "mode:standup" in payload["defaults"]["tags"]
        assert set(payload["calendar"]) == {"source", "length_weeks", "anchor_date", "current"}

    def test_unknown_mode_is_a_400(self, app):
        resp = request(app, "GET", "/api/context/options?mode=stanup")
        assert resp.code == 400 and "unknown mode" in json.loads(resp.body)["error"]


class TestPreview:
    def test_counts_window_and_summary(self, app, seeded):
        resp = request(app, "POST", "/api/context/preview", {"context": "standup@month", "rows": True})
        assert resp.code == 200, resp.body
        payload = json.loads(resp.body)
        assert set(payload) == {"scope", "window", "summary", "sources", "warnings"}
        assert payload["scope"]["sources"] == ["standup"] and payload["window"]["start"]
        standup = next(row for row in payload["sources"] if row["key"] == "standup")
        assert standup["count"] == 1
        assert standup["rows"][0]["project_label"] == "Apollo" and standup["rows"][0]["tags"] == ["q3"]
        assert "1 standup" in payload["summary"]

    def test_rows_are_omitted_by_default(self, app, seeded):
        payload = json.loads(request(app, "POST", "/api/context/preview", {"context": "all"}).body)
        assert all(row["rows"] == [] for row in payload["sources"])

    def test_a_typo_is_a_400_naming_the_sources(self, app):
        resp = request(app, "POST", "/api/context/preview", {"context": "stanup"})
        assert resp.code == 400 and "standup" in json.loads(resp.body)["error"]

    def test_unknown_mode_is_a_400(self, app):
        resp = request(app, "POST", "/api/context/preview", {"context": "all", "mode": "nope"})
        assert resp.code == 400


class TestLabels:
    def test_get_after_set(self, app, seeded):
        resp = request(
            app,
            "POST",
            "/api/sessions/standup/p1/labels",
            {"run_id": seeded, "project_label": "Zeus", "tags": ["Q4"]},
        )
        assert resp.code == 200, resp.body
        row = json.loads(resp.body)
        assert row["project_label"] == "Zeus" and row["tags"] == ["q3", "q4"]
        got = json.loads(request(app, "GET", f"/api/sessions/standup/p1/labels?run_id={seeded}").body)
        assert got == row

    def test_replace_tags(self, app, seeded):
        payload = {"run_id": seeded, "tags": ["only"], "merge_tags": False}
        row = json.loads(request(app, "POST", "/api/sessions/standup/p1/labels", payload).body)
        assert row["tags"] == ["only"]

    def test_missing_row_is_a_404(self, app):
        assert request(app, "GET", "/api/sessions/retro/p9/labels").code == 404

    def test_unknown_mode_is_a_400(self, app):
        assert request(app, "GET", "/api/sessions/nope/p1/labels").code == 400
        assert request(app, "POST", "/api/sessions/nope/p1/labels", {}).code == 400

    def test_bad_tags_are_a_400(self, app):
        resp = request(app, "POST", "/api/sessions/standup/p1/labels", {"tags": "q3"})
        assert resp.code == 400

    def test_every_context_route_is_registered_under_the_capability(self):
        from yeaboi.app.registry import ROUTES

        paths = {(r.method, r.path): r.capability for r in ROUTES}
        assert paths[("GET", "/api/context/options")] == "context"
        assert paths[("POST", "/api/context/preview")] == "context"
        assert paths[("GET", "/api/sessions/{mode}/{session_id}/labels")] == "context"
        assert paths[("POST", "/api/sessions/{mode}/{session_id}/labels")] == "context"
