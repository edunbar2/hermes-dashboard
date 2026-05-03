"""Kanban API — read-only board snapshot, task detail, and SSE updates."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..collectors.base import envelope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kanban", tags=["kanban"])

# Poll interval for the SSE change-detector. Cheap MAX(id) read; tune if
# the board ever feels laggy in practice.
_SSE_POLL_SECONDS = 1.5


@router.get("/board")
async def board(request: Request) -> dict[str, Any]:
    """Return the current 3-column board snapshot."""
    return await request.app.state.collectors["hermes_kanban"].collect()


@router.get("/tasks/{task_id}")
async def task_detail(task_id: str, request: Request) -> dict[str, Any]:
    """Return ``{task, comments, events}`` for a single card."""
    coll = request.app.state.collectors["hermes_kanban"]
    detail = await coll.get_task(task_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="task not found")
    return envelope("hermes_kanban_task", detail)


@router.get("/events")
async def events_stream(request: Request) -> StreamingResponse:
    """SSE stream — emits ``board`` events when ``task_events`` grows.

    The dashboard polls ``MAX(task_events.id)`` every 1.5s. When it advances
    we re-snapshot the board and push it. This keeps the page in sync with
    real agent activity without long-polling SQLite.
    """
    coll = request.app.state.collectors["hermes_kanban"]

    async def gen():
        last = await coll.latest_event_id()
        snap = await coll.collect()
        yield f"event: board\ndata: {json.dumps(snap)}\n\n"
        try:
            while True:
                await asyncio.sleep(_SSE_POLL_SECONDS)
                cur = await coll.latest_event_id()
                if cur != last:
                    last = cur
                    snap = await coll.collect()
                    yield f"event: board\ndata: {json.dumps(snap)}\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(gen(), media_type="text/event-stream")
