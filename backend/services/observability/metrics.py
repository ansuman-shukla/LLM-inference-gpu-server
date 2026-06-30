"""Prometheus metrics instrumentation."""

from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any

from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client import generate_latest as prometheus_generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS_TOTAL = Counter(
    "gpu_inference_http_requests_total",
    "Total HTTP requests handled by the FastAPI gateway.",
    ("method", "path", "status_code"),
    registry=REGISTRY,
)
HTTP_REQUEST_LATENCY_SECONDS = Histogram(
    "gpu_inference_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ("method", "path"),
    registry=REGISTRY,
)
STREAM_TTFT_SECONDS = Histogram(
    "gpu_inference_stream_ttft_seconds",
    "Streaming time to first token in seconds.",
    ("model",),
    registry=REGISTRY,
)
ACTIVE_STREAMS = Gauge(
    "gpu_inference_active_streams",
    "Currently active streaming responses.",
    registry=REGISTRY,
)
HTTP_429_TOTAL = Counter(
    "gpu_inference_http_429_total",
    "Total HTTP 429 responses.",
    ("error_code",),
    registry=REGISTRY,
)
HTTP_503_TOTAL = Counter(
    "gpu_inference_http_503_total",
    "Total HTTP 503 responses.",
    ("error_code",),
    registry=REGISTRY,
)
ANALYTICS_QUEUE_SIZE = Gauge(
    "gpu_inference_analytics_queue_size",
    "Current in-memory analytics queue size.",
    registry=REGISTRY,
)
CLICKHOUSE_FLUSH_FAILURES_TOTAL = Counter(
    "gpu_inference_clickhouse_flush_failures_total",
    "Total ClickHouse analytics flush failures after retries are exhausted.",
    registry=REGISTRY,
)
REDIS_FAILURES_TOTAL = Counter(
    "gpu_inference_redis_failures_total",
    "Total Redis dependency failures seen by admission/rate-limit code.",
    registry=REGISTRY,
)
VLLM_UPSTREAM_ERRORS_TOTAL = Counter(
    "gpu_inference_vllm_upstream_errors_total",
    "Total vLLM upstream timeout/status/response errors.",
    ("error_code",),
    registry=REGISTRY,
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record request count and latency for gateway HTTP traffic."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path == "/metrics":
            return await call_next(request)

        started_at = perf_counter()
        status_code = 500
        error_code: str | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            error_code = _error_code_from_response(response)
            return response
        except Exception as exc:
            status_code = int(getattr(exc, "status_code", 500))
            error_code = getattr(exc, "code", None)
            raise
        finally:
            record_http_request(
                method=request.method,
                path=_path_template(request),
                status_code=status_code,
                elapsed_seconds=perf_counter() - started_at,
                error_code=error_code,
            )


def record_http_request(
    *,
    method: str,
    path: str,
    status_code: int,
    elapsed_seconds: float,
    error_code: str | None = None,
) -> None:
    status = str(status_code)
    HTTP_REQUESTS_TOTAL.labels(method=method, path=path, status_code=status).inc()
    HTTP_REQUEST_LATENCY_SECONDS.labels(method=method, path=path).observe(elapsed_seconds)
    normalized_error_code = error_code or "unknown"
    if status_code == 429:
        HTTP_429_TOTAL.labels(error_code=normalized_error_code).inc()
    if status_code == 503:
        HTTP_503_TOTAL.labels(error_code=normalized_error_code).inc()


def record_stream_started() -> None:
    ACTIVE_STREAMS.inc()


def record_stream_finished() -> None:
    ACTIVE_STREAMS.dec()


def record_stream_ttft(*, model: str | None, ttft_seconds: float) -> None:
    STREAM_TTFT_SECONDS.labels(model=model or "unknown").observe(ttft_seconds)


def record_clickhouse_flush_failure() -> None:
    CLICKHOUSE_FLUSH_FAILURES_TOTAL.inc()


def record_redis_failure() -> None:
    REDIS_FAILURES_TOTAL.inc()


def record_vllm_upstream_error(error_code: str) -> None:
    VLLM_UPSTREAM_ERRORS_TOTAL.labels(error_code=error_code).inc()


def update_runtime_gauges(app_state: Any) -> None:
    collector = getattr(app_state, "analytics_collector", None)
    queue = getattr(collector, "queue", None)
    if queue is not None:
        ANALYTICS_QUEUE_SIZE.set(queue.qsize())


def generate_metrics() -> bytes:
    return prometheus_generate_latest(REGISTRY)


def metrics_response() -> Response:
    return Response(content=generate_metrics(), media_type=CONTENT_TYPE_LATEST)


def _path_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str):
        return path
    return request.url.path


def _error_code_from_response(response: Response) -> str | None:
    return response.headers.get("x-error-code")
