"""vLLM HTTP client."""

from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from backend.core.errors import AppError
from backend.services.vllm.errors import (
    invalid_response_error,
    timeout_error,
    upstream_status_error,
)

JsonObject = dict[str, Any]


class VLLMClient:
    """Async adapter for the vLLM OpenAI-compatible HTTP API."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float | None = None,
        connect_timeout_seconds: float = 10.0,
        read_timeout_seconds: float = 600.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        timeout: float | httpx.Timeout
        if timeout_seconds is not None:
            timeout = timeout_seconds
        else:
            timeout = httpx.Timeout(
                connect=connect_timeout_seconds,
                read=read_timeout_seconds,
                write=30.0,
                pool=10.0,
            )
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def list_models(self) -> JsonObject:
        """Return the upstream vLLM OpenAI-compatible model list."""
        try:
            response = await self._client.get("/v1/models")
        except httpx.TimeoutException as exc:
            raise timeout_error(exc) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                message="vLLM upstream request failed",
                code="upstream_error",
                status_code=502,
                type="server_error",
            ) from exc
        self._raise_for_upstream_status(response.status_code)
        try:
            parsed = response.json()
        except ValueError as exc:
            raise invalid_response_error() from exc
        if not isinstance(parsed, dict):
            raise invalid_response_error()
        return parsed

    async def create_chat_completion(self, payload: Mapping[str, Any]) -> JsonObject:
        """Create a non-streaming chat completion through vLLM."""
        response = await self._post_chat_completion(payload)
        try:
            parsed = response.json()
        except ValueError as exc:
            raise invalid_response_error() from exc
        if not isinstance(parsed, dict):
            raise invalid_response_error()
        return parsed

    async def stream_chat_completion(self, payload: Mapping[str, Any]) -> AsyncIterator[str]:
        """Stream chat completion SSE lines from vLLM."""
        stream_payload = {**payload, "stream": True}
        try:
            async with self._client.stream(
                "POST",
                "/v1/chat/completions",
                json=stream_payload,
            ) as response:
                self._raise_for_upstream_status(response.status_code)
                async for line in response.aiter_lines():
                    if line:
                        yield line
        except httpx.TimeoutException as exc:
            raise timeout_error(exc) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                message="vLLM upstream request failed",
                code="upstream_error",
                status_code=502,
                type="server_error",
            ) from exc

    async def _post_chat_completion(self, payload: Mapping[str, Any]) -> httpx.Response:
        try:
            response = await self._client.post("/v1/chat/completions", json=dict(payload))
        except httpx.TimeoutException as exc:
            raise timeout_error(exc) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                message="vLLM upstream request failed",
                code="upstream_error",
                status_code=502,
                type="server_error",
            ) from exc
        self._raise_for_upstream_status(response.status_code)
        return response

    @staticmethod
    def _raise_for_upstream_status(status_code: int) -> None:
        if status_code >= 400:
            raise upstream_status_error(status_code)
