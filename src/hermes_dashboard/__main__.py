"""Entry point: ``python -m hermes_dashboard`` or ``hermes-dashboard``."""
from __future__ import annotations

import logging

import uvicorn

from .app import create_app
from .config import DashboardConfig


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = DashboardConfig.from_env()
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
