"""The channel roster behind the Settings channel picker.

One rule carries the file: :func:`list_channels` never raises. A settings page
that offers a text box and says why is useful; one that 500s because a scope is
missing is not. So every failure — no token, a bad scope, a rate limit — is
asserted to come back as a reason with whatever was collected.
"""

from __future__ import annotations

import json

import pytest

from yeaboi.slack import channels
from yeaboi.tools import slack


class _Resp:
    def __init__(self, body: dict, status: int = 200, headers: dict | None = None):
        self._body = json.dumps(body).encode()
        self.status = status
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(slack.time, "sleep", lambda _s: None)


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(slack, "_token", lambda: "xoxb-test")


def _serve(monkeypatch, *responses):
    queue = list(responses)

    def fake(req, timeout=None):
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(slack.urllib.request, "urlopen", fake)


def _page(chans, cursor=""):
    body = {"ok": True, "channels": chans}
    if cursor:
        body["response_metadata"] = {"next_cursor": cursor}
    return _Resp(body)


class TestListChannels:
    def test_no_token_asks_for_one_instead_of_failing(self, monkeypatch):
        monkeypatch.setattr(slack, "_token", lambda: "")
        result = channels.list_channels()
        assert result["channels"] == []
        assert "SLACK_BOT_TOKEN" in result["reason"]

    def test_one_page_comes_back_sorted(self, monkeypatch):
        _serve(
            monkeypatch,
            _page([{"id": "C2", "name": "zebra"}, {"id": "C1", "name": "alpha", "is_private": True}]),
        )
        result = channels.list_channels()
        assert [c["name"] for c in result["channels"]] == ["alpha", "zebra"]
        assert result["channels"][0] == {"id": "C1", "name": "alpha", "is_private": True}
        assert result["reason"] == ""

    def test_a_cursor_is_followed(self, monkeypatch):
        _serve(
            monkeypatch,
            _page([{"id": "C1", "name": "one"}], cursor="next"),
            _page([{"id": "C2", "name": "two"}]),
        )
        assert [c["name"] for c in channels.list_channels()["channels"]] == ["one", "two"]

    def test_archived_channels_are_dropped(self, monkeypatch):
        _serve(
            monkeypatch,
            _page([{"id": "C1", "name": "live"}, {"id": "C2", "name": "old", "is_archived": True}]),
        )
        assert [c["name"] for c in channels.list_channels()["channels"]] == ["live"]

    def test_a_missing_scope_is_a_reason_not_a_crash(self, monkeypatch):
        _serve(monkeypatch, _Resp({"ok": False, "error": "missing_scope"}))
        result = channels.list_channels()
        assert result["channels"] == []
        assert "missing_scope" in result["reason"]

    def test_a_rate_limit_keeps_what_it_collected(self, monkeypatch):
        """A big workspace still gets a usable picker rather than nothing."""
        _serve(
            monkeypatch,
            _page([{"id": "C1", "name": "one"}], cursor="next"),
            _Resp({"ok": False, "error": "ratelimited"}, status=429, headers={"Retry-After": "1"}),
        )
        result = channels.list_channels()
        assert [c["name"] for c in result["channels"]] == ["one"]
        assert "ratelimited" in result["reason"]


class TestConversationsList:
    def test_it_asks_for_both_channel_kinds_and_skips_archived(self, monkeypatch):
        seen: list = []

        def fake(req, timeout=None):
            seen.append(req.full_url)
            return _Resp({"ok": True, "channels": []})

        monkeypatch.setattr(slack.urllib.request, "urlopen", fake)
        slack.conversations_list()
        assert "conversations.list" in seen[0]
        assert "public_channel" in seen[0] and "private_channel" in seen[0]
        assert "exclude_archived=True" in seen[0]
