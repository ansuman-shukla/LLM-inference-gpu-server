"""Batch queue integration."""

from typing import Any

BATCH_QUEUE_KEY = "batch_queue:pending"


class RedisBatchQueue:
    def __init__(self, redis: Any, *, queue_key: str = BATCH_QUEUE_KEY) -> None:
        self._redis = redis
        self._queue_key = queue_key

    async def enqueue(self, job_id: str) -> None:
        await self._redis.rpush(self._queue_key, job_id)

    async def dequeue(self) -> str | None:
        value = await self._redis.lpop(self._queue_key)
        return str(value) if value is not None else None

    async def contains(self, job_id: str) -> bool:
        values = await self._redis.lrange(self._queue_key, 0, -1)
        return job_id in {str(value) for value in values}


class InMemoryBatchQueue:
    def __init__(self, *, fail_enqueue: bool = False) -> None:
        self.job_ids: list[str] = []
        self.fail_enqueue = fail_enqueue

    async def enqueue(self, job_id: str) -> None:
        if self.fail_enqueue:
            raise RuntimeError("redis enqueue failed")
        if job_id not in self.job_ids:
            self.job_ids.append(job_id)

    async def dequeue(self) -> str | None:
        if not self.job_ids:
            return None
        return self.job_ids.pop(0)

    async def contains(self, job_id: str) -> bool:
        return job_id in self.job_ids
