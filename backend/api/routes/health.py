"""Health check routes."""

from fastapi import APIRouter, Request

from backend.core.errors import AppError

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Return service health."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> dict[str, str]:
    """Return readiness after application startup has completed."""
    if not getattr(request.app.state, "ready", False):
        raise AppError(
            message="Service is not ready",
            code="service_not_ready",
            status_code=503,
            type="server_error",
        )
    redis_client = getattr(request.app.state, "redis_client", None)
    if redis_client is not None:
        try:
            await redis_client.ping()
        except Exception as exc:
            raise AppError(
                message="Redis dependency is unavailable",
                code="dependency_unavailable",
                status_code=503,
                type="server_error",
            ) from exc
    return {"status": "ready"}
