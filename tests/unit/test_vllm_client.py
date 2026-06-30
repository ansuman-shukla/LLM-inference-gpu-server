"""Tests for the vLLM client adapter."""

import asyncio
import json
from typing import Any

import httpx
import pytest

from backend.core.errors import AppError
from backend.services.vllm.client import VLLMClient


CHAT_PAYLOAD = {
    "model": "test-model",
    "messages": [{"role": "user", "content": "hello"}],
}


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_non_streaming_payload_is_forwarded() -> None:
    captured: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "cmpl_1", "choices": []})

    async def scenario() -> dict[str, Any]:
        client = VLLMClient(
            "http://vllm.test",
            transport=httpx.MockTransport(handler),
        )
        try:
            return await client.create_chat_completion(CHAT_PAYLOAD)
        finally:
            await client.close()

    response = run(scenario())

    assert response == {"id": "cmpl_1", "choices": []}
    assert captured == {
        "method": "POST",
        "path": "/v1/chat/completions",
        "payload": CHAT_PAYLOAD,
    }


def test_upstream_timeout_maps_to_504() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    async def scenario() -> None:
        client = VLLMClient(
            "http://vllm.test",
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.create_chat_completion(CHAT_PAYLOAD)
        finally:
            await client.close()

    with pytest.raises(AppError) as exc_info:
        run(scenario())

    assert exc_info.value.status_code == 504
    assert exc_info.value.code == "upstream_timeout"


def test_upstream_500_maps_to_502() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    async def scenario() -> None:
        client = VLLMClient(
            "http://vllm.test",
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.create_chat_completion(CHAT_PAYLOAD)
        finally:
            await client.close()

    with pytest.raises(AppError) as exc_info:
        run(scenario())

    assert exc_info.value.status_code == 502
    assert exc_info.value.code == "upstream_error"
