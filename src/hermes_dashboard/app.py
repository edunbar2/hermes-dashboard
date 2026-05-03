"""FastAPI app factory."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import DashboardConfig

STATIC_DIR = Path(__file__).parent / "static"


def create_app(config: DashboardConfig | None = None) -> FastAPI:
    """Build the FastAPI app. Pass a config for tests; defaults to env."""
    config = config or DashboardConfig.from_env()
    app = FastAPI(title="Hermes Dashboard", version="0.1.0")
    app.state.config = config

    app.mount(
        "/static", StaticFiles(directory=STATIC_DIR), name="static"
    )

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
