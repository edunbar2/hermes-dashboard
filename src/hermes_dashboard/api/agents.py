"""Agent roster, avatar, and live activity endpoints."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from ..agents import avatar_path, get_agent, roster_payload
from ..collectors.base import envelope

router = APIRouter(prefix="/api/agents", tags=["agents"])
_SSE_POLL_SECONDS = 2.0


@router.get("/roster")
async def roster() -> dict[str, Any]:
    return envelope("agent_roster", {"agents": roster_payload()})


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    return await request.app.state.collectors["agent_activity"].collect()


@router.get("/{agent_id}/avatar")
async def avatar(agent_id: str, request: Request) -> FileResponse:
    if get_agent(agent_id) is None:
        raise HTTPException(status_code=404, detail="unknown agent")
    path = avatar_path(request.app.state.config.profiles_dir, agent_id)
    if path is None:
        raise HTTPException(status_code=404, detail="avatar not found")
    return FileResponse(path)


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    coll = request.app.state.collectors["agent_activity"]

    async def gen():
        last = await coll.latest_event_id()
        snap = await coll.collect()
        yield f"event: agents\ndata: {json.dumps(snap)}\n\n"
        try:
            while True:
                await asyncio.sleep(_SSE_POLL_SECONDS)
                cur = await coll.latest_event_id()
                if cur != last:
                    last = cur
                    snap = await coll.collect()
                    yield f"event: agents\ndata: {json.dumps(snap)}\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(gen(), media_type="text/event-stream")
