"""Application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from backend.api.routes.batch_jobs import router as batch_jobs_router
from backend.api.routes.chat_completions import router as chat_completions_router
from backend.api.routes.health import router as health_router
from backend.api.routes.metrics import router as metrics_router
from backend.api.routes.models import router as models_router
from backend.core.config import Settings, get_settings
from backend.core.lifecycle import shutdown, startup
from backend.middlewares.auth import PROTECTED_PATHS, ApiKeyAuthMiddleware
from backend.middlewares.error_handler import install_error_handlers
from backend.middlewares.request_id import RequestIdMiddleware
from backend.services.observability.metrics import MetricsMiddleware
from backend.services.vllm.client import VLLMClient


def create_app(
    settings: Settings | None = None,
    vllm_client: Any | None = None,
    auth_service: Any | None = None,
    admission_service: Any | None = None,
    token_estimator: Any | None = None,
    audit_service: Any | None = None,
    analytics_collector: Any | None = None,
    batch_service: Any | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application."""
    resolved_settings = settings or get_settings()
    owns_vllm_client = vllm_client is None

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
        app_instance.state.vllm_client = vllm_client or VLLMClient(
            resolved_settings.vllm_base_url,
            connect_timeout_seconds=resolved_settings.vllm_connect_timeout_seconds,
            read_timeout_seconds=resolved_settings.vllm_read_timeout_seconds,
        )
        await startup(app_instance, resolved_settings)
        try:
            yield
        finally:
            if owns_vllm_client:
                await app_instance.state.vllm_client.close()
            await shutdown(app_instance)

    app_instance = FastAPI(
        title="GPU Inference Backend",
        description=(
            "OpenAI-compatible GPU inference API. Use the Swagger Authorize button with "
            "an `an_...` API key for protected inference and batch endpoints."
        ),
        version="0.1.0",
        lifespan=lifespan,
        swagger_ui_parameters={"persistAuthorization": True, "displayRequestDuration": True},
    )
    if auth_service is not None:
        app_instance.state.auth_service = auth_service
    if admission_service is not None:
        app_instance.state.admission_service = admission_service
    if token_estimator is not None:
        app_instance.state.token_estimator = token_estimator
    if audit_service is not None:
        app_instance.state.audit_service = audit_service
    if analytics_collector is not None:
        app_instance.state.analytics_collector = analytics_collector
    if batch_service is not None:
        app_instance.state.batch_service = batch_service
    app_instance.add_middleware(ApiKeyAuthMiddleware)
    app_instance.add_middleware(RequestIdMiddleware)
    app_instance.add_middleware(MetricsMiddleware)
    install_error_handlers(app_instance)
    app_instance.include_router(health_router)
    app_instance.include_router(models_router)
    app_instance.include_router(metrics_router)
    app_instance.include_router(chat_completions_router)
    app_instance.include_router(batch_jobs_router)
    app_instance.openapi = lambda: _custom_openapi(app_instance)  # type: ignore[method-assign]
    return app_instance


def _custom_openapi(app_instance: FastAPI) -> dict[str, Any]:
    if app_instance.openapi_schema:
        return app_instance.openapi_schema

    schema = get_openapi(
        title=app_instance.title,
        version=app_instance.version,
        description=app_instance.description,
        routes=app_instance.routes,
    )
    components = schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "API key",
        "description": "Use `Authorization: Bearer an_...`.",
    }

    for path, methods in schema.get("paths", {}).items():
        if not _is_openapi_protected_path(path):
            continue
        for operation in methods.values():
            if isinstance(operation, dict):
                operation["security"] = [{"BearerAuth": []}]

    app_instance.openapi_schema = schema
    return app_instance.openapi_schema


def _is_openapi_protected_path(path: str) -> bool:
    return any(
        path == protected or path.startswith(f"{protected}/") for protected in PROTECTED_PATHS
    )


app = create_app()
