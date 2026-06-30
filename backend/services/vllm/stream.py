"""vLLM streaming helpers."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress

DONE_LINE = "data: [DONE]"
HEARTBEAT_INTERVAL_SECONDS = 15.0
SSE_MEDIA_TYPE = "text/event-stream"
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def format_sse_data(data: str) -> str:
    """Format a server-sent event data line."""
    return f"data: {data}\n\n"


def format_heartbeat() -> str:
    """Format a valid SSE heartbeat comment."""
    return ": heartbeat\n\n"


async def stream_with_heartbeats(
    lines: AsyncIterator[str],
    *,
    interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    """Yield upstream lines, emitting heartbeat comments while waiting."""
    iterator = lines.__aiter__()
    next_line: asyncio.Future[str] = asyncio.ensure_future(anext(iterator))
    try:
        while True:
            try:
                line = await asyncio.wait_for(asyncio.shield(next_line), timeout=interval_seconds)
            except TimeoutError:
                yield format_heartbeat()
                continue
            except StopAsyncIteration:
                break
            yield line
            next_line = asyncio.ensure_future(anext(iterator))
    finally:
        if not next_line.done():
            next_line.cancel()
            with suppress(asyncio.CancelledError):
                await next_line
        aclose = getattr(iterator, "aclose", None)
        if aclose is not None:
            await aclose()


async def ensure_done_event(lines: AsyncIterator[str]) -> AsyncIterator[str]:
    """Yield upstream SSE lines and append [DONE] when upstream did not send it."""
    sent_done = False
    async for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == DONE_LINE:
            sent_done = True
        yield stripped if stripped.endswith("\n\n") else f"{stripped}\n\n"
    if not sent_done:
        yield format_sse_data("[DONE]")
