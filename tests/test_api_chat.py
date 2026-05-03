"""Tests for the chat proxy endpoints."""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from hermes_dashboard.api import chat as chat_module


def _make_response(status_code: int, json_body: dict[str, Any] | None = None,
                   text: str = "", headers: dict[str, str] | None = None) -> httpx.Response:
    """Build an httpx.Response without a real network call."""
    request = httpx.Request("POST", "http://127.0.0.1:8642/v1/chat/completions")
    if json_body is not None:
        return httpx.Response(
            status_code, json=json_body, request=request, headers=headers or {}
        )
    return httpx.Response(
        status_code, text=text, request=request, headers=headers or {}
    )


class _StubAsyncClient:
    """Minimal stand-in for httpx.AsyncClient used by the chat module."""

    def __init__(self, responder, *args, **kwargs):
        self._responder = responder
        self.last_post = None
        self.last_get = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, *, json=None, headers=None):
        self.last_post = {"url": url, "json": json, "headers": headers}
        return self._responder("POST", url, json, headers)

    async def get(self, url, *, headers=None):
        self.last_get = {"url": url, "headers": headers}
        return self._responder("GET", url, None, headers)


@pytest.fixture
def patch_httpx(monkeypatch):
    """Install a fake AsyncClient and capture the request the module makes."""
    captured: dict[str, Any] = {}

    def install(responder):
        def factory(*args, **kwargs):
            client = _StubAsyncClient(responder, *args, **kwargs)
            captured["client"] = client
            return client

        monkeypatch.setattr(chat_module.httpx, "AsyncClient", factory)
        return captured

    return install


def test_send_chat_happy_path(client, patch_httpx):
    """A normal turn returns the assistant reply and forwards the session id."""
    def responder(method, url, json, headers):
        assert method == "POST"
        assert url.endswith("/v1/chat/completions")
        assert json["messages"] == [{"role": "user", "content": "hello"}]
        assert headers["X-Hermes-Session-Id"] == "sess-123"
        return _make_response(
            200,
            json_body={
                "choices": [{"message": {"content": "hi back"}}],
                "model": "hermes-agent",
            },
            headers={"X-Hermes-Session-Id": "sess-123"},
        )

    patch_httpx(responder)
    resp = client.post(
        "/api/chat/send",
        json={"message": "hello", "session_id": "sess-123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["reply"] == "hi back"
    assert body["session_id"] == "sess-123"
    assert body["model"] == "hermes-agent"


def test_send_chat_no_session_id(client, patch_httpx):
    """Without a session id, no header is sent and a fresh response is returned."""
    captured_headers = {}

    def responder(method, url, json, headers):
        captured_headers.update(headers)
        return _make_response(
            200,
            json_body={
                "choices": [{"message": {"content": "fresh"}}],
                "model": "hermes-agent",
            },
            headers={"X-Hermes-Session-Id": "new-sess"},
        )

    patch_httpx(responder)
    resp = client.post("/api/chat/send", json={"message": "hi"})
    assert resp.status_code == 200
    assert "X-Hermes-Session-Id" not in captured_headers
    assert resp.json()["session_id"] == "new-sess"


def test_send_chat_upstream_error_surfaces(client, patch_httpx):
    """A 500 from api_server becomes a 500 with the body in the detail."""
    def responder(method, url, json, headers):
        return _make_response(500, text="boom")

    patch_httpx(responder)
    resp = client.post("/api/chat/send", json={"message": "hi"})
    assert resp.status_code == 500
    assert "boom" in resp.json()["detail"]


def test_send_chat_unreachable_returns_502(client, patch_httpx):
    """Connection errors get translated to a 502 with the URL in the message."""
    def responder(method, url, json, headers):
        raise httpx.ConnectError("connection refused")

    patch_httpx(responder)
    resp = client.post("/api/chat/send", json={"message": "hi"})
    assert resp.status_code == 502
    assert "unreachable" in resp.json()["detail"].lower()


def test_send_chat_rejects_empty_message(client):
    """Pydantic should reject empty input before we make any upstream call."""
    resp = client.post("/api/chat/send", json={"message": ""})
    assert resp.status_code == 422


def test_chat_health_reachable(client, patch_httpx):
    """When api_server is up, /api/chat/health reports reachable=true."""
    def responder(method, url, json, headers):
        assert method == "GET"
        assert url == "http://127.0.0.1:8642/health"
        return _make_response(200, json_body={"status": "ok", "platform": "hermes-agent"})

    patch_httpx(responder)
    resp = client.get("/api/chat/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["reachable"] is True
    assert body["body"]["status"] == "ok"


def test_chat_health_unreachable(client, patch_httpx):
    """Network errors are reported gracefully, not as 5xx."""
    def responder(method, url, json, headers):
        raise httpx.ConnectError("nope")

    patch_httpx(responder)
    resp = client.get("/api/chat/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["reachable"] is False
    assert "nope" in body["error"]
