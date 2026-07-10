"""Unit tests for the Retro LAN server: share codes, token auth, lifecycle."""

import json
import urllib.error
import urllib.request

import pytest

from scrum_agent.retro.board import RetroBoard
from scrum_agent.retro.server import (
    RetroServer,
    decode_share_code,
    encode_share_code,
    get_lan_ip,
    make_token,
)


class TestShareCode:
    def test_roundtrip(self):
        ip, port, tok = "192.168.1.24", 5173, make_token()
        code = encode_share_code(ip, port, tok)
        assert decode_share_code(code) == (ip, port, tok)

    def test_roundtrip_tolerates_spacing_and_case(self):
        ip, port, tok = "10.0.0.5", 5199, "abc-DEF_123"
        code = encode_share_code(ip, port, tok)
        assert decode_share_code(code.lower().replace("-", " ")) == (ip, port, tok)

    def test_token_is_unguessable_length(self):
        assert len(make_token()) >= 16
        assert make_token() != make_token()


class TestLanIp:
    def test_returns_ipv4_string(self):
        ip = get_lan_ip()
        assert isinstance(ip, str)
        assert ip.count(".") == 3


@pytest.fixture
def running_server():
    b = RetroBoard("s", "Proj")
    srv = RetroServer(b, port=5210)
    srv.start()
    try:
        yield srv, b
    finally:
        srv.stop()


def _get(url):
    return urllib.request.urlopen(url, timeout=5)


class TestServerRouting:
    def test_get_root_serves_html(self, running_server):
        srv, _ = running_server
        html = _get(f"http://127.0.0.1:{srv.port}/").read().decode()
        assert "<title>Sprint Retro</title>" in html

    def test_api_without_token_forbidden(self, running_server):
        srv, _ = running_server
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(f"http://127.0.0.1:{srv.port}/api/cards")
        assert exc.value.code == 403

    def test_api_with_token_returns_cards(self, running_server):
        srv, b = running_server
        b.add_card(grid="went_well", text="hello", author="Sam")
        data = json.load(_get(f"http://127.0.0.1:{srv.port}/api/cards?token={srv.token}"))
        assert data["revision"] >= 1
        assert data["cards"][0]["text"] == "hello"

    def test_post_adds_card(self, running_server):
        srv, b = running_server
        body = json.dumps({"grid": "demos", "text": "new UI", "author": "Rae"}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{srv.port}/api/cards?token={srv.token}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = json.load(urllib.request.urlopen(req, timeout=5))
        assert resp["ok"] and resp["card"]["grid"] == "demos"
        assert b.total() == 1

    def test_post_without_token_forbidden(self, running_server):
        srv, _ = running_server
        req = urllib.request.Request(
            f"http://127.0.0.1:{srv.port}/api/cards",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 403

    def test_unknown_path_404(self, running_server):
        srv, _ = running_server
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(f"http://127.0.0.1:{srv.port}/nope")
        assert exc.value.code == 404


def _post(srv, path, body, *, token=None):
    tok = srv.token if token is None else token
    req = urllib.request.Request(
        f"http://127.0.0.1:{srv.port}{path}?token={tok}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.load(urllib.request.urlopen(req, timeout=5))


class TestStateEndpoint:
    def test_state_shape(self, running_server):
        srv, b = running_server
        b.add_card(grid="went_well", text="ci", author="Sam")
        data = json.load(_get(f"http://127.0.0.1:{srv.port}/api/state?token={srv.token}"))
        assert set(data) == {"revision", "cards", "presence", "typing", "timer"}

    def test_state_forbidden_without_token(self, running_server):
        srv, _ = running_server
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(f"http://127.0.0.1:{srv.port}/api/state")
        assert exc.value.code == 403


class TestReactEndpoint:
    def test_toggle(self, running_server):
        srv, b = running_server
        c = b.add_card(grid="went_well", text="ci", author="Sam")
        r = _post(srv, "/api/react", {"card_id": c.id, "emoji": "👍", "pid": "p1"})
        assert r["reacted"] is True and r["state"]["cards"][0]["reactions"] == {"👍": 1}
        r = _post(srv, "/api/react", {"card_id": c.id, "emoji": "👍", "pid": "p1"})
        assert r["reacted"] is False and r["state"]["cards"][0]["reactions"] == {}

    def test_forbidden_without_token(self, running_server):
        srv, _ = running_server
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(srv, "/api/react", {"card_id": "x", "emoji": "👍", "pid": "p"}, token="")
        assert exc.value.code == 403


class TestPresenceEndpoint:
    def test_records_and_returns_state(self, running_server):
        srv, _ = running_server
        state = _post(srv, "/api/presence", {"pid": "p1", "name": "Sam", "avatar": "🤠", "typing_grid": "demos"})
        assert any(p["name"] == "Sam" for p in state["presence"])
        assert any(t["grid"] == "demos" for t in state["typing"])


class TestTimerEndpoint:
    def test_start_and_stop(self, running_server):
        srv, _ = running_server
        r = _post(srv, "/api/timer", {"action": "start", "duration": 120, "pid": "p1"})
        assert r["state"]["timer"]["running"] is True
        r = _post(srv, "/api/timer", {"action": "stop", "pid": "p1"})
        assert r["state"]["timer"]["running"] is False


class TestCardsReturnsState:
    def test_post_card_returns_state(self, running_server):
        srv, _ = running_server
        r = _post(srv, "/api/cards", {"grid": "demos", "text": "new UI", "author": "Rae"})
        assert r["ok"] and "state" in r and r["state"]["cards"][0]["text"] == "new UI"


class TestTokenFreePage:
    def test_served_page_has_no_token(self, running_server):
        srv, _ = running_server
        page = _get(f"http://127.0.0.1:{srv.port}/").read().decode()
        assert srv.token not in page  # GET / is unauthenticated — must not leak the token


class TestJoinCode:
    def test_right_code_returns_token(self, running_server):
        srv, _ = running_server
        # /api/join is unauthenticated (no token in the URL).
        req = urllib.request.Request(
            f"http://127.0.0.1:{srv.port}/api/join",
            data=json.dumps({"code": srv.join_code}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        assert json.load(urllib.request.urlopen(req, timeout=5))["token"] == srv.token

    def test_wrong_code_forbidden(self, running_server):
        srv, _ = running_server
        req = urllib.request.Request(
            f"http://127.0.0.1:{srv.port}/api/join",
            data=json.dumps({"code": "WRONG-XXX"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 403


class TestQrEndpoint:
    def test_token_gated(self, running_server):
        srv, _ = running_server
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(f"http://127.0.0.1:{srv.port}/api/qr")
        assert exc.value.code == 403

    def test_returns_svg(self, running_server):
        srv, _ = running_server
        body = _get(f"http://127.0.0.1:{srv.port}/api/qr?token={srv.token}").read()
        assert b"<svg" in body  # segno inline SVG


class TestCardMutations:
    def test_edit_author_only(self, running_server):
        srv, _ = running_server
        r = _post(srv, "/api/cards", {"grid": "went_well", "text": "x", "author": "Sam", "pid": "p1"})
        cid = r["card"]["id"]
        with pytest.raises(urllib.error.HTTPError) as exc:  # wrong pid → 403
            _post(srv, "/api/card/edit", {"card_id": cid, "text": "y", "pid": "p2"})
        assert exc.value.code == 403
        ok = _post(srv, "/api/card/edit", {"card_id": cid, "text": "y", "pid": "p1"})
        assert ok["ok"] and ok["state"]["cards"][0]["text"] == "y"

    def test_delete_author_only(self, running_server):
        srv, _ = running_server
        cid = _post(srv, "/api/cards", {"grid": "demos", "text": "x", "author": "a", "pid": "p1"})["card"]["id"]
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(srv, "/api/card/delete", {"card_id": cid, "pid": "p2"})
        assert exc.value.code == 403
        assert _post(srv, "/api/card/delete", {"card_id": cid, "pid": "p1"})["ok"] is True

    def test_move_open_to_anyone(self, running_server):
        srv, _ = running_server
        cid = _post(srv, "/api/cards", {"grid": "went_well", "text": "x", "author": "a", "pid": "p1"})["card"]["id"]
        r = _post(srv, "/api/card/move", {"card_id": cid, "grid": "demos", "index": 0, "pid": "someone-else"})
        assert r["ok"] and r["state"]["cards"][0]["grid"] == "demos"


class TestLifecycle:
    def test_properties_expose_join_info(self):
        srv = RetroServer(RetroBoard("s"), port=5211)
        assert srv.url.startswith("http://")
        assert "?token=" in srv.url
        assert len(srv.display_code) == 9  # "XXXX-XXXX"

    def test_start_stop_idempotent_stop(self):
        srv = RetroServer(RetroBoard("s"), port=5212)
        srv.start()
        srv.stop()
        srv.stop()  # second stop is a no-op, must not raise
