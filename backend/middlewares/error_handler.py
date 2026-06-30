"""Error handling middleware."""

import logging
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ExceptionHandler

from backend.core.constants import REQUEST_ID_HEADER
from backend.core.errors import AppError, openai_error_object
from backend.services.observability.sentry import capture_request_exception

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _error_response(
    request: Request,
    *,
    status_code: int,
    message: str,
    code: str,
    error_type: str,
    param: str | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    headers = {"x-error-code": code}
    if request_id is not None:
        headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(
        status_code=status_code,
        content=openai_error_object(
            message=message,
            code=code,
            error_type=error_type,
            param=param,
            request_id=request_id,
        ),
        headers=headers,
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    capture_request_exception(request, exc)
    return _error_response(
        request,
        status_code=exc.status_code,
        message=exc.message,
        code=exc.code,
        error_type=exc.type,
        param=exc.param,
    )


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "HTTP error"
    return _error_response(
        request,
        status_code=exc.status_code,
        message=message,
        code="http_error",
        error_type="invalid_request_error" if exc.status_code < 500 else "server_error",
    )


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return _error_response(
        request,
        status_code=400,
        message="Invalid request payload",
        code="bad_request",
        error_type="invalid_request_error",
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled application error", exc_info=exc)
    capture_request_exception(request, exc)
    return _error_response(
        request,
        status_code=500,
        message="Internal server error",
        code="internal_server_error",
        error_type="server_error",
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register global error handlers."""
    app.add_exception_handler(AppError, cast(ExceptionHandler, app_error_handler))
    app.add_exception_handler(StarletteHTTPException, cast(ExceptionHandler, http_error_handler))
    app.add_exception_handler(
        RequestValidationError, cast(ExceptionHandler, validation_error_handler)
    )
    app.add_exception_handler(Exception, unhandled_error_handler)
