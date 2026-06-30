"""Tests for SSE stream helpers."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from backend.services.vllm.stream import (
    ensure_done_event,
    format_heartbeat,
    format_sse_data,
    stream_with_heartbeats,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_sse_chunk_formatter_is_correct() -> None:
    assert format_sse_data('{"ok":true}') == 'data: {"ok":true}\n\n'


def test_heartbeat_event_is_valid() -> None:
    assert format_heartbeat() == ": heartbeat\n\n"


def test_stream_with_heartbeats_emits_heartbeat_while_waiting() -> None:
    async def source() -> AsyncIterator[str]:
        await asyncio.sleep(0.01)
        yield 'data: {"chunk":1}'

    async def first_event() -> str:
        async for event in stream_with_heartbeats(source(), interval_seconds=0.001):
            return event
        raise AssertionError("stream ended before yielding")

    assert run(first_event()) == ": heartbeat\n\n"


def test_stream_with_heartbeats_closes_source_on_cancel() -> None:
    closed = False

    async def source() -> AsyncIterator[str]:
        nonlocal closed
        try:
            yield 'data: {"chunk":1}'
            await asyncio.sleep(1)
        finally:
            closed = True

    async def scenario() -> bool:
        stream = stream_with_heartbeats(source(), interval_seconds=0.001)
        assert await anext(stream) == 'data: {"chunk":1}'
        await stream.aclose()
        return closed

    assert run(scenario()) is True


def test_done_event_is_appended_when_missing() -> None:
    async def source() -> AsyncIterator[str]:
        yield 'data: {"chunk":1}'

    async def collect() -> list[str]:
        return [event async for event in ensure_done_event(source())]

    assert run(collect()) == ['data: {"chunk":1}\n\n', "data: [DONE]\n\n"]


def test_done_event_is_not_duplicated() -> None:
    async def source() -> AsyncIterator[str]:
        yield 'data: {"chunk":1}'
        yield "data: [DONE]"

    async def collect() -> list[str]:
        return [event async for event in ensure_done_event(source())]

    assert run(collect()) == ['data: {"chunk":1}\n\n', "data: [DONE]\n\n"]
