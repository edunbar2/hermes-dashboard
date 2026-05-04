"""FastAPI app factory."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import agents as api_agents
from .api import chat as api_chat
from .api import hermes as api_hermes
from .api import kanban as api_kanban
from .api import system as api_system
from .api import tasks as api_tasks
from .collectors import build_registry
from .config import DashboardConfig
from .safe_paths import resolve_child, resolve_root

STATIC_DIR = resolve_root(Path(__file__).parent / "static")
INDEX_HTML = resolve_child(STATIC_DIR, "index.html")


def create_app(config: DashboardConfig | None = None) -> FastAPI:
    """Build the FastAPI app. Pass a config for tests; defaults to env."""
    config = config or DashboardConfig.from_env()
    app = FastAPI(title="Hermes Dashboard", version="0.1.0")
    app.state.config = config
    app.state.collectors = build_registry(config.hermes_home)

    app.mount(
        "/static", StaticFiles(directory=STATIC_DIR), name="static"
    )

    app.include_router(api_system.router)
    app.include_router(api_hermes.router)
    app.include_router(api_agents.router)
    app.include_router(api_tasks.router)
    app.include_router(api_chat.router)
    app.include_router(api_kanban.router)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(INDEX_HTML)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
