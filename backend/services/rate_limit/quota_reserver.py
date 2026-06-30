"""Quota reservation service."""

import logging
from dataclasses import dataclass
from typing import Protocol, cast

from backend.core.errors import AppError
from backend.db.redis import RedisLike
from backend.services.rate_limit.rate_limiter import _redis_call, tpm_key

logger = logging.getLogger(__name__)
TPM_WINDOW_SECONDS = 60


class TokenReservationLike(Protocol):
    reserved_tokens: int

    async def finalize(self, *, actual_tokens: int, release_all: bool = False) -> None: ...


@dataclass
class TokenReservation:
    """Redis-backed token reservation that releases unused estimated tokens."""

    redis: RedisLike
    key: str
    reserved_tokens: int
    finalized: bool = False

    async def finalize(self, *, actual_tokens: int, release_all: bool = False) -> None:
        if self.finalized:
            return
        self.finalized = True
        tokens_to_release = (
            self.reserved_tokens if release_all else self.reserved_tokens - actual_tokens
        )
        if tokens_to_release <= 0:
            return
        try:
            remaining = await self.redis.decrby(self.key, tokens_to_release)
            if remaining <= 0:
                await self.redis.delete(self.key)
        except Exception:
            logger.exception("failed to finalize token reservation")


@dataclass
class NoopTokenReservation:
    reserved_tokens: int = 0

    async def finalize(self, *, actual_tokens: int, release_all: bool = False) -> None:
        return None


class QuotaReserver:
    """Redis-backed token-per-minute reservation service."""

    def __init__(self, redis: RedisLike | None = None, *, tpm_limit: int = 60_000) -> None:
        self._redis = redis
        self._tpm_limit = tpm_limit

    async def reserve(self, *, api_key_id: str, estimated_tokens: int = 0) -> TokenReservationLike:
        if self._redis is None or estimated_tokens <= 0:
            return NoopTokenReservation(reserved_tokens=max(estimated_tokens, 0))

        key = tpm_key(api_key_id)
        count = cast(int, await _redis_call(self._redis.incrby(key, estimated_tokens)))
        if count == estimated_tokens:
            await _redis_call(self._redis.expire(key, TPM_WINDOW_SECONDS))
        if count > self._tpm_limit:
            try:
                await self._redis.decrby(key, estimated_tokens)
            except Exception:
                logger.exception("failed to roll back rejected token reservation")
            raise AppError(
                message="Token rate limit exceeded",
                code="token_rate_limit_exceeded",
                status_code=429,
                type="rate_limit_error",
            )
        return TokenReservation(redis=self._redis, key=key, reserved_tokens=estimated_tokens)
