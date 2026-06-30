"""Application error types."""

from dataclasses import dataclass
from typing import Any


@dataclass
class AppError(Exception):
    """Application exception rendered as an OpenAI-compatible error."""

    message: str
    code: str
    status_code: int = 500
    type: str = "server_error"
    param: str | None = None


def openai_error_object(
    *,
    message: str,
    code: str,
    error_type: str,
    param: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build the error object shape expected by OpenAI-compatible clients."""
    error: dict[str, Any] = {
        "message": message,
        "type": error_type,
        "param": param,
        "code": code,
    }
    if request_id is not None:
        error["request_id"] = request_id
    return {"error": error}
