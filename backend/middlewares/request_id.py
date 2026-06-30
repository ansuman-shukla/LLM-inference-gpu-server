"""Request ID middleware."""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core.constants import REQUEST_ID_HEADER
from backend.core.request_context import request_id_context
from backend.utils.ids import generate_request_id


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a request ID to request state, response headers, and log context."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or generate_request_id()
        request.state.request_id = request_id
        token = request_id_context.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_context.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
