"""Tests for chat completion request mapping."""

from backend.schemas.chat_completion import ChatCompletionRequest
from backend.services.vllm.payload_mapper import normalize_chat_completion_payload


def test_valid_payload_creates_normalized_internal_request() -> None:
    request = ChatCompletionRequest(
        model="test-model",
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=16,
    )

    payload = normalize_chat_completion_payload(request)

    assert payload == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": False,
        "max_tokens": 16,
    }


def test_multimodal_payload_preserves_image_parts_and_response_format() -> None:
    request = ChatCompletionRequest(
        model="test-model",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "classify this image"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64,ZmFrZQ=="},
                    },
                ],
            }
        ],
        response_format={"type": "json_object"},
    )

    payload = normalize_chat_completion_payload(request)

    assert payload == {
        "model": "test-model",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "classify this image"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64,ZmFrZQ=="},
                    },
                ],
            }
        ],
        "stream": False,
        "response_format": {"type": "json_object"},
    }
