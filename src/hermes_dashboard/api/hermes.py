"""Hermes-specific endpoints: gateway status, sessions, cron, aggregate."""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/hermes", tags=["hermes"])


@router.get("/status")
async def status(request: Request) -> dict:
    return await request.app.state.collectors["hermes_status"].collect()


@router.get("/gateway")
async def gateway(request: Request) -> dict:
    return await request.app.state.collectors["hermes_gateway"].collect()


@router.get("/sessions")
async def sessions(request: Request, limit: int = 20) -> dict:
    return await request.app.state.collectors["hermes_sessions"].collect(limit=limit)


@router.get("/cron")
async def cron(request: Request) -> dict:
    return await request.app.state.collectors["hermes_cron"].collect()
