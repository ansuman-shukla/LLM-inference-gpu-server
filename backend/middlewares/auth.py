"""Authentication middleware."""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core.config import Settings
from backend.core.constants import REQUEST_ID_HEADER
from backend.core.errors import AppError, openai_error_object
from backend.db.postgres import create_postgres_engine, create_sessionmaker
from backend.repositories.api_key_repository import ApiKeyRepository
from backend.services.auth.api_key_service import AuthContext, ApiKeyService, missing_api_key_error

AUTHORIZATION_PREFIX = "Bearer "
PROTECTED_PATHS = (
    "/v1/chat/completions",
    "/v1/completions",
    "/v1/embeddings",
    "/v1/batch",
)


class AuthService(Protocol):
    async def authenticate(self, raw_key: str) -> AuthContext: ...


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate protected API routes with Bearer API keys."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not _is_protected_path(request.url.path):
            return await call_next(request)

        try:
            raw_key = _extract_bearer_token(request)
            if raw_key is None:
                raise missing_api_key_error()

            auth_service = _get_or_create_auth_service(request.app.state)
            request.state.auth_context = await auth_service.authenticate(raw_key)
        except AppError as exc:
            return _app_error_response(request, exc)
        return await call_next(request)


def _is_protected_path(path: str) -> bool:
    return any(
        path == protected or path.startswith(f"{protected}/") for protected in PROTECTED_PATHS
    )


def _extract_bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization")
    if authorization is None or not authorization.startswith(AUTHORIZATION_PREFIX):
        return None
    raw_key = authorization.removeprefix(AUTHORIZATION_PREFIX).strip()
    return raw_key or None


def _get_or_create_auth_service(app_state: Any) -> AuthService:
    auth_service = getattr(app_state, "auth_service", None)
    if auth_service is not None:
        return auth_service

    settings: Settings = app_state.settings
    engine = create_postgres_engine(settings.database_url)
    app_state.postgres_engine = engine
    auth_service = ApiKeyService(
        ApiKeyRepository,
        create_sessionmaker(engine),
        key_prefix=settings.api_key_prefix,
    )
    app_state.auth_service = auth_service
    return auth_service


def _app_error_response(request: Request, exc: AppError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    headers = {"x-error-code": exc.code}
    if request_id is not None:
        headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(
        status_code=exc.status_code,
        content=openai_error_object(
            message=exc.message,
            code=exc.code,
            error_type=exc.type,
            param=exc.param,
            request_id=request_id,
        ),
        headers=headers,
    )
