"""Analytics flusher worker entrypoint."""

import asyncio
import signal
from contextlib import suppress

from backend.core.config import get_settings
from backend.db.clickhouse import ClickHouseClient
from backend.services.observability.sentry import capture_exception, initialize_sentry
from backend.services.analytics.clickhouse_flusher import ClickHouseFlusher
from backend.services.analytics.event_collector import AnalyticsCollector


async def main() -> None:
    settings = get_settings()
    initialize_sentry(settings)
    collector = AnalyticsCollector(max_size=settings.analytics_queue_size)
    client = ClickHouseClient.from_settings(
        url=settings.clickhouse_url,
        database=settings.clickhouse_database,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        secure=settings.clickhouse_secure,
        verify=settings.clickhouse_verify,
    )
    flusher = ClickHouseFlusher(
        collector=collector,
        client=client,
        batch_size=settings.analytics_flush_batch_size,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    flusher_task = asyncio.create_task(flusher.run_forever())
    stop_task = asyncio.create_task(stop_event.wait())
    done, _ = await asyncio.wait(
        {flusher_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if flusher_task in done:
        stop_task.cancel()
        await flusher_task
        return

    await flusher.stop()
    flusher_task.cancel()
    with suppress(asyncio.CancelledError):
        await flusher_task


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        capture_exception(exc, tags={"component": "analytics_flusher"})
        raise
