"""Application lifecycle hooks."""

import logging

from fastapi import FastAPI

from backend.core.config import Settings
from backend.core.logging import configure_logging
from backend.services.observability.sentry import initialize_sentry

logger = logging.getLogger(__name__)


async def startup(app: FastAPI, settings: Settings) -> None:
    """Initialize application runtime state."""
    configure_logging(settings.log_level)
    app.state.sentry_enabled = initialize_sentry(settings)
    app.state.settings = settings
    app.state.ready = True
    logger.info("application startup complete")


async def shutdown(app: FastAPI) -> None:
    """Tear down application runtime state."""
    app.state.ready = False
    postgres_engine = getattr(app.state, "postgres_engine", None)
    if postgres_engine is not None:
        await postgres_engine.dispose()
    redis_client = getattr(app.state, "redis_client", None)
    if redis_client is not None:
        await redis_client.aclose()
    logger.info("application shutdown complete")
