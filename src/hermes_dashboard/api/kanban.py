"""Kanban API — read-only board snapshot, task detail, and SSE updates."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..collectors.base import envelope
from .. import state as dash_state

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


@router.post("/archive")
async def archive_done(request: Request) -> dict[str, Any]:
    """Bump the end-of-day archive watermark.

    Hit by a Hermes cron job at 23:59 daily, but idempotent and safe to
    call ad-hoc ("clear the board now"). Sets the watermark to ``now()``
    so the next ``/board`` snapshot drops every Done card completed
    before this moment. We never write to Hermes' kanban DB itself —
    the watermark lives in our own state file under HERMES_HOME.
    """
    cfg = request.app.state.config
    ts = dash_state.set_archive_watermark(cfg.hermes_home)
    logger.info("kanban archive watermark advanced to %d", ts)
    return {"archived_at": ts, "watermark": ts}


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
