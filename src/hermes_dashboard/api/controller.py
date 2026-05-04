"""Controller API — read-only projection of Hermes Controller v0."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..collectors.base import envelope

router = APIRouter(prefix="/api/controller", tags=["controller"])


@router.get("/board")
async def board(request: Request) -> dict[str, Any]:
    """Return read-only Controller v0 board projection."""
    return await request.app.state.collectors["hermes_controller"].collect()


@router.get("/tasks/{task_id}")
async def task_detail(task_id: str, request: Request) -> dict[str, Any]:
    """Return controller task detail with events and artifact refs."""
    coll = request.app.state.collectors["hermes_controller"]
    detail = await coll.get_task(task_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="controller task not found")
    return envelope("hermes_controller_task", detail)
