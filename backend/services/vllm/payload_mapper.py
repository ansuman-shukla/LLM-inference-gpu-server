"""vLLM payload mapping."""

from typing import Any

from backend.schemas.chat_completion import ChatCompletionRequest


def normalize_chat_completion_payload(request: ChatCompletionRequest) -> dict[str, Any]:
    """Convert validated API input to the payload sent to vLLM."""
    return request.model_dump(exclude_none=True)
