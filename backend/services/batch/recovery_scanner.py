"""Batch recovery scanner."""

from backend.services.batch.batch_service import BatchJobStore, BatchQueue


class BatchRecoveryScanner:
    def __init__(self, *, store: BatchJobStore, queue: BatchQueue) -> None:
        self.store = store
        self.queue = queue

    async def reenqueue_missing(self, *, limit: int = 100) -> int:
        requeued = 0
        for job in await self.store.list_recoverable(limit=limit):
            if await self.queue.contains(job.id):
                continue
            await self.queue.enqueue(job.id)
            requeued += 1
        return requeued
