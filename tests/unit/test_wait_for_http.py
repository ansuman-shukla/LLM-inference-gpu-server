"""Tests for the generic HTTP readiness helper."""

import asyncio

import httpx

from backend.scripts.wait_for_http import wait_for_http


def test_wait_for_http_returns_on_success() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    async def scenario() -> None:
        transport = httpx.MockTransport(handler)
        original_client = httpx.AsyncClient

        class TestClient(httpx.AsyncClient):
            def __init__(self, *args: object, **kwargs: object) -> None:
                super().__init__(*args, transport=transport, **kwargs)

        httpx.AsyncClient = TestClient  # type: ignore[assignment]
        try:
            await wait_for_http(
                "http://service.test/health", timeout_seconds=0.1, interval_seconds=0.01
            )
        finally:
            httpx.AsyncClient = original_client  # type: ignore[assignment]

    asyncio.run(scenario())
