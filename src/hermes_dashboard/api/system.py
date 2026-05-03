"""System metrics endpoints: one-shot JSON + 1Hz SSE stream."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/metrics")
async def metrics(request: Request) -> dict:
    """Return a single point-in-time system snapshot."""
    return await request.app.state.collectors["system"].collect()


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    """Server-sent-events stream — emits a snapshot every ~1s."""
    collector = request.app.state.collectors["system"]

    async def generator():
        try:
            while True:
                snap = await collector.collect()
                yield f"data: {json.dumps(snap)}\n\n"
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            return

    return StreamingResponse(generator(), media_type="text/event-stream")
