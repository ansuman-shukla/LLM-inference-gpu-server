"""Request admission service backed by Redis."""

from dataclasses import dataclass
from typing import Protocol

from backend.services.auth.api_key_service import AuthContext
from backend.services.rate_limit.concurrency_limiter import ConcurrencyLimiter
from backend.services.rate_limit.quota_reserver import QuotaReserver, TokenReservationLike
from backend.services.rate_limit.rate_limiter import RateLimiter


class Releasable(Protocol):
    async def release(self) -> None: ...


@dataclass
class AdmissionLease:
    """Admission state held until a request leaves the GPU path."""

    concurrency: Releasable
    token_reservation: TokenReservationLike

    async def release(self) -> None:
        await self.concurrency.release()

    async def finalize_tokens(self, *, actual_tokens: int, release_all: bool = False) -> None:
        await self.token_reservation.finalize(actual_tokens=actual_tokens, release_all=release_all)


class AdmissionService:
    """Runs overload, RPM, concurrency, and TPM placeholder checks before vLLM."""

    def __init__(
        self,
        *,
        rate_limiter: RateLimiter,
        concurrency_limiter: ConcurrencyLimiter,
        quota_reserver: QuotaReserver,
        rpm_limit: int,
        concurrent_request_limit: int,
    ) -> None:
        self._rate_limiter = rate_limiter
        self._concurrency_limiter = concurrency_limiter
        self._quota_reserver = quota_reserver
        self._rpm_limit = rpm_limit
        self._concurrent_request_limit = concurrent_request_limit

    async def admit(
        self, auth_context: AuthContext, *, estimated_tokens: int = 0
    ) -> AdmissionLease:
        await self._rate_limiter.check_overload()
        await self._rate_limiter.check_rpm(
            api_key_id=auth_context.api_key_id, limit=self._rpm_limit
        )
        concurrency = await self._concurrency_limiter.acquire(
            api_key_id=auth_context.api_key_id,
            limit=self._concurrent_request_limit,
        )
        token_reservation = await self._quota_reserver.reserve(
            api_key_id=auth_context.api_key_id,
            estimated_tokens=estimated_tokens,
        )
        return AdmissionLease(concurrency=concurrency, token_reservation=token_reservation)


class NoopAdmissionService:
    """Test helper for routes where admission control is not under test."""

    async def admit(
        self, auth_context: AuthContext, *, estimated_tokens: int = 0
    ) -> AdmissionLease:
        return AdmissionLease(
            concurrency=_NoopConcurrencyLease(),
            token_reservation=await QuotaReserver().reserve(
                api_key_id=auth_context.api_key_id, estimated_tokens=estimated_tokens
            ),
        )


class _NoopConcurrencyLease:
    async def release(self) -> None:
        return None
