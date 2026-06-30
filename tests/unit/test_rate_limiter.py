"""Tests for rate limiting."""

import asyncio

import pytest

from backend.core.errors import AppError
from backend.services.rate_limit.concurrency_limiter import ConcurrencyLimiter, concurrency_key
from backend.services.rate_limit.rate_limiter import RateLimiter, rpm_key, tpm_key
from tests.conftest import FakeRedis


def test_rate_limit_key_names_are_stable() -> None:
    assert rpm_key("key_123") == "rl:api_key:key_123:rpm"
    assert tpm_key("key_123") == "rl:api_key:key_123:tpm"
    assert concurrency_key("key_123") == "concurrent:api_key:key_123"


def test_concurrency_counter_increments_and_decrements() -> None:
    redis = FakeRedis()
    limiter = ConcurrencyLimiter(redis)

    async def scenario() -> None:
        lease = await limiter.acquire(api_key_id="key_123", limit=1)
        assert redis.values[concurrency_key("key_123")] == 1
        await lease.release()

    asyncio.run(scenario())
    assert concurrency_key("key_123") not in redis.values


def test_redis_unavailable_maps_to_503_dependency_unavailable() -> None:
    limiter = RateLimiter(FakeRedis(fail=True))

    async def scenario() -> None:
        await limiter.check_rpm(api_key_id="key_123", limit=1)

    with pytest.raises(AppError) as exc_info:
        asyncio.run(scenario())

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "dependency_unavailable"
