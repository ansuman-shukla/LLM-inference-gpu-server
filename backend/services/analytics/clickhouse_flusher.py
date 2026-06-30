"""ClickHouse analytics flusher."""

import asyncio
import logging
from collections import defaultdict
from typing import Protocol

from backend.services.analytics.event_collector import AnalyticsCollector
from backend.services.analytics.event_models import (
    AnalyticsEvent,
    AnalyticsTable,
    columns_for_table,
)
from backend.services.observability.metrics import record_clickhouse_flush_failure
from backend.services.observability.sentry import capture_exception

logger = logging.getLogger(__name__)


class ClickHouseInsertClient(Protocol):
    def insert(
        self, table: str, rows: list[tuple[object, ...]], column_names: list[str]
    ) -> None: ...


class ClickHouseFlusher:
    """Batch flusher for analytics events."""

    def __init__(
        self,
        *,
        collector: AnalyticsCollector,
        client: ClickHouseInsertClient,
        batch_size: int = 500,
        flush_interval_seconds: float = 2.0,
        max_retries: int = 3,
    ) -> None:
        self.collector = collector
        self.client = client
        self.batch_size = batch_size
        self.flush_interval_seconds = flush_interval_seconds
        self.max_retries = max_retries
        self.flush_failures = 0
        self._stopped = asyncio.Event()

    async def flush_once(self) -> bool:
        events = self.collector.drain_batch(self.batch_size)
        if not events:
            return True
        try:
            await self._insert_with_retry(events)
            return True
        except Exception as exc:
            self.flush_failures += 1
            record_clickhouse_flush_failure()
            logger.exception("clickhouse analytics flush failed")
            capture_exception(
                exc,
                tags={
                    "component": "analytics_flusher",
                    "error_code": "clickhouse_flush_failed",
                },
                context={
                    "flush_failures": self.flush_failures,
                    "event_count": len(events),
                    "tables": sorted({event.table for event in events}),
                },
            )
            self.collector.requeue_front(events)
            return False

    async def run_forever(self) -> None:
        while not self._stopped.is_set():
            await self.flush_once()
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self.flush_interval_seconds)
            except TimeoutError:
                continue

    async def stop(self) -> None:
        self._stopped.set()
        await self.flush_once()

    async def _insert_with_retry(self, events: list[AnalyticsEvent]) -> None:
        delay = 0.1
        for attempt in range(self.max_retries):
            try:
                self._insert(events)
                return
            except Exception:
                if attempt == self.max_retries - 1:
                    raise
                await asyncio.sleep(delay)
                delay *= 2

    def _insert(self, events: list[AnalyticsEvent]) -> None:
        grouped: dict[AnalyticsTable, list[tuple[object, ...]]] = defaultdict(list)
        for event in events:
            grouped[event.table].append(event.to_row())
        for table, rows in grouped.items():
            self.client.insert(table, rows, column_names=columns_for_table(table))
