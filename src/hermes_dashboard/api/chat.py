"""Chat proxy — forwards messages to the Hermes api_server adapter.

The api_server adapter exposes an OpenAI-compatible interface on
``http://127.0.0.1:8642/v1``. This module proxies dashboard chat requests
to it, optionally pinning a session via the ``X-Hermes-Session-Id`` header
so that follow-ups continue the same conversation.

We do NOT add auth here; the dashboard is intended for LAN-only use behind
the host firewall. If that ever changes, slot a dependency in front of the
router.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatSendRequest(BaseModel):
    """Payload for ``POST /api/chat/send``."""

    message: str = Field(..., min_length=1, description="User message text")
    session_id: str | None = Field(
        default=None,
        description=(
            "Optional Hermes session id. When provided, the api_server "
            "continues that conversation; otherwise it starts a fresh one."
        ),
    )
    model: str = Field(
        default="hermes-agent",
        description="Model id — only 'hermes-agent' is exposed today.",
    )


class ChatSendResponse(BaseModel):
    """Response from ``POST /api/chat/send``."""

    reply: str
    session_id: str | None = None
    model: str
    raw: dict[str, Any] | None = None


def _api_server_url(request: Request) -> str:
    """Return the configured api_server base URL (e.g. ``.../v1``)."""
    return request.app.state.config.api_server_url.rstrip("/")


@router.post("/send", response_model=ChatSendResponse)
async def send_chat(payload: ChatSendRequest, request: Request) -> ChatSendResponse:
    """Send a single user turn and return the assistant reply.

    This is a synchronous, non-streaming proxy — fine for short messages and
    the dashboard's "kick off a project" use case. Streaming can be added
    later by wiring up SSE relay against ``/v1/runs/{id}/events``.
    """
    base = _api_server_url(request)
    headers = {"Content-Type": "application/json"}
    if payload.session_id:
        headers["X-Hermes-Session-Id"] = payload.session_id

    body = {
        "model": payload.model,
        "messages": [{"role": "user", "content": payload.message}],
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{base}/chat/completions", json=body, headers=headers
            )
    except httpx.RequestError as exc:
        logger.warning("api_server unreachable at %s: %s", base, exc)
        raise HTTPException(
            status_code=502,
            detail=f"Hermes api_server unreachable at {base}: {exc}",
        ) from exc

    if resp.status_code >= 400:
        # Surface the upstream error verbatim so the UI can show it.
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"api_server error: {resp.text[:500]}",
        )

    data = resp.json()
    try:
        reply = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"api_server returned unexpected payload: {data}",
        ) from exc

    # The api_server echoes the session id back in this header when it
    # creates one; reuse on subsequent turns to maintain continuity.
    session_id = (
        resp.headers.get("X-Hermes-Session-Id")
        or payload.session_id
    )

    return ChatSendResponse(
        reply=reply,
        session_id=session_id,
        model=data.get("model", payload.model),
        raw=data,
    )


@router.get("/health")
async def chat_health(request: Request) -> dict[str, Any]:
    """Probe the upstream api_server.

    Returns ``{"reachable": true}`` if the api_server's ``/health`` endpoint
    responds, plus the resolved base URL so the UI can show what it's
    talking to.
    """
    base = _api_server_url(request)
    # /health lives at the root, not under /v1 — strip the version suffix.
    health_url = base.rsplit("/", 1)[0] + "/health" if base.endswith("/v1") else f"{base}/health"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(health_url)
        reachable = resp.status_code == 200
        body = resp.json() if reachable else None
    except httpx.RequestError as exc:
        return {
            "reachable": False,
            "url": health_url,
            "error": str(exc),
        }

    return {
        "reachable": reachable,
        "url": health_url,
        "status_code": resp.status_code,
        "body": body,
    }
