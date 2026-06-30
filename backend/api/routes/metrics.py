"""Metrics routes."""

from fastapi import APIRouter, Request
from fastapi.responses import Response

from backend.services.observability.metrics import metrics_response, update_runtime_gauges

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    """Expose Prometheus metrics for private scraping."""
    update_runtime_gauges(request.app.state)
    return metrics_response()
