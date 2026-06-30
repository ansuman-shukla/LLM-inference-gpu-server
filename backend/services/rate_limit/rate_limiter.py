"""Rate limiter service."""

from typing import Any, cast

from backend.core.errors import AppError
from backend.db.redis import RedisLike
from backend.services.observability.metrics import record_redis_failure

RPM_WINDOW_SECONDS = 60


def rpm_key(api_key_id: str) -> str:
    return f"rl:api_key:{api_key_id}:rpm"


def tpm_key(api_key_id: str) -> str:
    return f"rl:api_key:{api_key_id}:tpm"


def overload_key() -> str:
    return "overload:global"


class RateLimiter:
    """Redis-backed request-per-minute limiter and overload gate."""

    def __init__(self, redis: RedisLike) -> None:
        self._redis = redis

    async def check_overload(self) -> None:
        value = await _redis_call(self._redis.get(overload_key()))
        if value is not None and str(value).lower() not in {"", "0", "false", "none"}:
            raise AppError(
                message="Server is overloaded",
                code="server_overloaded",
                status_code=503,
                type="server_error",
            )

    async def check_rpm(self, *, api_key_id: str, limit: int) -> None:
        key = rpm_key(api_key_id)
        count = cast(int, await _redis_call(self._redis.incr(key)))
        if count == 1:
            await _redis_call(self._redis.expire(key, RPM_WINDOW_SECONDS))
        if count > limit:
            raise AppError(
                message="Rate limit exceeded",
                code="rate_limit_exceeded",
                status_code=429,
                type="rate_limit_error",
            )


async def _redis_call(awaitable: Any) -> Any:
    try:
        return await awaitable
    except AppError:
        raise
    except Exception as exc:
        record_redis_failure()
        raise AppError(
            message="Redis dependency is unavailable",
            code="dependency_unavailable",
            status_code=503,
            type="server_error",
        ) from exc
