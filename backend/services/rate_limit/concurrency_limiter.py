"""Concurrency limiter service."""

import logging
from dataclasses import dataclass
from typing import cast

from backend.core.errors import AppError
from backend.db.redis import RedisLike
from backend.services.rate_limit.rate_limiter import _redis_call

logger = logging.getLogger(__name__)


def concurrency_key(api_key_id: str) -> str:
    return f"concurrent:api_key:{api_key_id}"


@dataclass
class ConcurrencyLease:
    """Acquired concurrency slot that can be released once."""

    redis: RedisLike
    key: str
    released: bool = False

    async def release(self) -> None:
        if self.released:
            return
        self.released = True
        try:
            remaining = await self.redis.decr(self.key)
            if remaining <= 0:
                await self.redis.delete(self.key)
        except Exception:
            logger.exception("failed to release concurrency slot")


class ConcurrencyLimiter:
    """Redis-backed concurrent request limiter."""

    def __init__(self, redis: RedisLike) -> None:
        self._redis = redis

    async def acquire(self, *, api_key_id: str, limit: int) -> ConcurrencyLease:
        key = concurrency_key(api_key_id)
        count = cast(int, await _redis_call(self._redis.incr(key)))
        if count > limit:
            try:
                await self._redis.decr(key)
            except Exception:
                logger.exception("failed to roll back rejected concurrency slot")
            raise AppError(
                message="Concurrent request limit exceeded",
                code="concurrency_limit_exceeded",
                status_code=429,
                type="rate_limit_error",
            )
        return ConcurrencyLease(redis=self._redis, key=key)
