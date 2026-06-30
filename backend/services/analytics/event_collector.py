"""Analytics event collector."""

import asyncio
import logging
from typing import Protocol

from backend.services.analytics.event_models import AnalyticsEvent
from backend.services.analytics.spool import LocalAnalyticsSpool

logger = logging.getLogger(__name__)


class AnalyticsSpool(Protocol):
    async def write(self, event: AnalyticsEvent) -> None: ...


class AnalyticsCollector:
    """Bounded in-memory analytics queue."""

    def __init__(self, *, max_size: int = 1000, spool: AnalyticsSpool | None = None) -> None:
        self.queue: asyncio.Queue[AnalyticsEvent] = asyncio.Queue(maxsize=max_size)
        self.spool = spool or LocalAnalyticsSpool()
        self.dropped_non_critical = 0
        self.spooled_critical = 0

    def collect(self, event: AnalyticsEvent) -> bool:
        """Queue an event without blocking the request path."""
        try:
            self.queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            if event.critical:
                self.spooled_critical += 1
                asyncio.create_task(self._safe_spool(event))
            else:
                self.dropped_non_critical += 1
            return False

    async def _safe_spool(self, event: AnalyticsEvent) -> None:
        try:
            await self.spool.write(event)
        except Exception:
            logger.exception("failed to spool critical analytics event")

    def drain_batch(self, batch_size: int) -> list[AnalyticsEvent]:
        events: list[AnalyticsEvent] = []
        while len(events) < batch_size:
            try:
                events.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events

    def requeue_front(self, events: list[AnalyticsEvent]) -> None:
        for event in events:
            try:
                self.queue.put_nowait(event)
            except asyncio.QueueFull:
                if event.critical:
                    asyncio.create_task(self._safe_spool(event))
                else:
                    self.dropped_non_critical += 1
