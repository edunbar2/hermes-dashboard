"""Dashboard task request API.

These endpoints create and track dashboard-owned task requests. They do not
write to Hermes' kanban.db; Hermione can later bridge requests into real Hermes
kanban work through the approved agent/tool path.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import state as dash_state
from ..agents import normalize_agent
from ..collectors.base import envelope

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
_SSE_POLL_SECONDS = 2.0


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(default="", max_length=5000)
    priority: int = Field(default=2, ge=1, le=5)
    preferred_agent: str | None = Field(default=None, max_length=64)


class TaskPatch(BaseModel):
    status: Literal["assigned", "todo", "ready", "running", "blocked", "done", "cancelled"] | None = None
    selected_agent: str | None = Field(default=None, max_length=64)
    assignee: str | None = Field(default=None, max_length=64)
    handoff_status: Literal["awaiting_hermione", "queued", "submitted", "rejected", "linked"] | None = None
    hermes_task_id: str | None = Field(default=None, max_length=128)
    body: str | None = Field(default=None, max_length=5000)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    priority: int | None = Field(default=None, ge=1, le=5)


def _dashboard_task_card(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "body": task.get("body"),
        "priority": task.get("priority", 2),
        "created_by": task.get("created_by", "dashboard"),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "status": task.get("status", "assigned"),
        "assignee": task.get("assignee") or "Hermione",
        "selected_agent": task.get("selected_agent"),
        "preferred_agent": task.get("preferred_agent"),
        "hermes_task_id": task.get("hermes_task_id"),
        "handoff_status": task.get("handoff_status", "awaiting_hermione"),
        "source": "dashboard",
    }


def _empty_columns() -> list[dict[str, Any]]:
    return [
        {"name": "Assigned / Awaiting Hermione", "tasks": []},
        {"name": "Queued / Assigned", "tasks": []},
        {"name": "In Progress", "tasks": []},
        {"name": "Done", "tasks": []},
    ]


async def _combined_board(request: Request) -> dict[str, Any]:
    cfg = request.app.state.config
    columns = _empty_columns()
    by_name = {c["name"]: c for c in columns}

    # Dashboard-created requests first: canonical state is dashboard-state.json.
    for task in dash_state.list_dashboard_tasks(cfg.hermes_home):
        card = _dashboard_task_card(task)
        status = str(card.get("status") or "assigned")
        if status == "done":
            by_name["Done"]["tasks"].append(card)
        elif status in {"running", "blocked"}:
            by_name["In Progress"]["tasks"].append(card)
        elif card.get("selected_agent"):
            by_name["Queued / Assigned"]["tasks"].append(card)
        else:
            by_name["Assigned / Awaiting Hermione"]["tasks"].append(card)

    # Merge the read-only Hermes kanban projection.
    kanban = await request.app.state.collectors["hermes_kanban"].collect()
    data = kanban.get("data", {})
    if data.get("available"):
        for col in data.get("columns", []):
            target = by_name.get(col.get("name"))
            if target is None:
                continue
            for task in col.get("tasks", []):
                card = dict(task)
                card.setdefault("source", "hermes")
                target["tasks"].append(card)

    return envelope(
        "dashboard_tasks",
        {
            "available": True,
            "columns": columns,
            "total": sum(len(c["tasks"]) for c in columns),
            "done_auto_archive_days": 3,
        },
    )


@router.get("/board")
async def board(request: Request) -> dict[str, Any]:
    return await _combined_board(request)


@router.post("")
async def create_task(payload: TaskCreate, request: Request) -> dict[str, Any]:
    preferred = normalize_agent(payload.preferred_agent) if payload.preferred_agent else None
    task = dash_state.create_dashboard_task(
        request.app.state.config.hermes_home,
        title=payload.title,
        body=payload.body,
        priority=payload.priority,
        preferred_agent=preferred,
    )
    return envelope("dashboard_task_created", {"task": task})


@router.patch("/{task_id}")
async def patch_task(task_id: str, payload: TaskPatch, request: Request) -> dict[str, Any]:
    updates = payload.model_dump(exclude_unset=True)
    if "selected_agent" in updates and updates["selected_agent"]:
        updates["selected_agent"] = normalize_agent(updates["selected_agent"]) or updates["selected_agent"]
    if "assignee" in updates and updates["assignee"]:
        updates["assignee"] = normalize_agent(updates["assignee"]) or updates["assignee"]
    task = dash_state.update_dashboard_task(request.app.state.config.hermes_home, task_id, **updates)
    if task is None:
        raise HTTPException(status_code=404, detail="dashboard task not found")
    return envelope("dashboard_task_updated", {"task": task})


@router.post("/archive")
async def archive_done(request: Request) -> dict[str, Any]:
    count = dash_state.archive_done_dashboard_tasks(request.app.state.config.hermes_home, older_than_days=3)
    return {"archived": count, "older_than_days": 3}


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    kanban = request.app.state.collectors["hermes_kanban"]

    async def gen():
        last = await kanban.latest_event_id()
        snap = await _combined_board(request)
        yield f"event: board\ndata: {json.dumps(snap)}\n\n"
        try:
            while True:
                await asyncio.sleep(_SSE_POLL_SECONDS)
                cur = await kanban.latest_event_id()
                if cur != last:
                    last = cur
                    snap = await _combined_board(request)
                    yield f"event: board\ndata: {json.dumps(snap)}\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(gen(), media_type="text/event-stream")
