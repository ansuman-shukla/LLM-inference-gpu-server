"""vLLM error mapping."""

import httpx

from backend.core.errors import AppError
from backend.services.observability.metrics import record_vllm_upstream_error


def timeout_error(exc: httpx.TimeoutException) -> AppError:
    """Map an upstream timeout to the public API error contract."""
    record_vllm_upstream_error("upstream_timeout")
    return AppError(
        message="vLLM upstream timed out",
        code="upstream_timeout",
        status_code=504,
        type="server_error",
    )


def upstream_status_error(status_code: int) -> AppError:
    """Map an unexpected upstream HTTP status to the public API error contract."""
    record_vllm_upstream_error("upstream_error")
    return AppError(
        message=f"vLLM upstream returned HTTP {status_code}",
        code="upstream_error",
        status_code=502,
        type="server_error",
    )


def invalid_response_error() -> AppError:
    """Map malformed upstream responses to the public API error contract."""
    record_vllm_upstream_error("upstream_invalid_response")
    return AppError(
        message="vLLM upstream returned an invalid response",
        code="upstream_invalid_response",
        status_code=502,
        type="server_error",
    )
