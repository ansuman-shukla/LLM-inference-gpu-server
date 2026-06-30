"""Integration tests for the vLLM adapter with a fake upstream."""

import asyncio
from typing import Any

import httpx
from fastapi import FastAPI

from backend.services.vllm.client import VLLMClient


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_fake_vllm_returns_non_streaming_response_through_adapter() -> None:
    fake_vllm = FastAPI()

    @fake_vllm.post("/v1/chat/completions")
    async def chat_completion(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": "chatcmpl_fake",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "hello from fake vllm"},
                    "finish_reason": "stop",
                }
            ],
        }

    async def scenario() -> dict[str, Any]:
        client = VLLMClient(
            "http://fake-vllm.test",
            transport=httpx.ASGITransport(app=fake_vllm),
        )
        try:
            return await client.create_chat_completion(
                {
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "hello"}],
                }
            )
        finally:
            await client.close()

    response = run(scenario())

    assert response["id"] == "chatcmpl_fake"
    assert response["model"] == "test-model"
    assert response["choices"][0]["message"]["content"] == "hello from fake vllm"


def test_fake_vllm_models_endpoint_responds_through_adapter() -> None:
    fake_vllm = FastAPI()

    @fake_vllm.get("/v1/models")
    async def models() -> dict[str, Any]:
        return {"object": "list", "data": [{"id": "test-model", "object": "model"}]}

    async def scenario() -> dict[str, Any]:
        client = VLLMClient(
            "http://fake-vllm.test",
            transport=httpx.ASGITransport(app=fake_vllm),
        )
        try:
            return await client.list_models()
        finally:
            await client.close()

    response = run(scenario())

    assert response["object"] == "list"
    assert response["data"][0]["id"] == "test-model"
