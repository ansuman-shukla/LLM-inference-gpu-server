"""Integration tests for streaming chat completions."""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from backend.api.routes.chat_completions import _stream_response
from backend.main import create_app
from tests.conftest import (
    audit_service_for_tests,
    auth_headers,
    auth_service_for_tests,
    noop_admission_service,
)


class FakeStreamingVLLMClient:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None

    async def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("streaming route should not call non-streaming client method")

    async def stream_chat_completion(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        self.payload = payload
        yield 'data: {"choices":[{"delta":{"content":"hel"}}]}'
        yield 'data: {"choices":[{"delta":{"content":"lo"}}]}'


def test_fake_streaming_vllm_returns_chunks_through_fastapi() -> None:
    fake_client = FakeStreamingVLLMClient()
    app = create_app(
        vllm_client=fake_client,
        auth_service=auth_service_for_tests(),
        admission_service=noop_admission_service(),
        audit_service=audit_service_for_tests(),
    )

    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            },
            headers=auth_headers(),
        ) as response:
            body = response.read().decode("utf-8")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert 'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n' in body
    assert 'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n' in body
    assert body.endswith("data: [DONE]\n\n")
    assert isinstance(app.state.last_stream_ttft_ms, int)
    assert fake_client.payload == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
    }


def test_disconnect_cleanup_path_closes_upstream_stream() -> None:
    closed = False

    class DisconnectingRequest:
        def __init__(self) -> None:
            self.calls = 0
            self.state = SimpleNamespace()
            self.app = SimpleNamespace(state=SimpleNamespace())

        async def is_disconnected(self) -> bool:
            self.calls += 1
            return self.calls > 1

    class ClosableStreamingClient:
        async def stream_chat_completion(self, payload: dict[str, Any]) -> AsyncIterator[str]:
            nonlocal closed
            try:
                yield 'data: {"choices":[{"delta":{"content":"first"}}]}'
                yield 'data: {"choices":[{"delta":{"content":"second"}}]}'
            finally:
                closed = True

    async def scenario() -> bool:
        stream = _stream_response(
            ClosableStreamingClient(), {"stream": True}, DisconnectingRequest()
        )
        assert await anext(stream) == 'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
        try:
            await anext(stream)
        except StopAsyncIteration:
            pass
        return closed

    import asyncio

    assert asyncio.run(scenario()) is True
