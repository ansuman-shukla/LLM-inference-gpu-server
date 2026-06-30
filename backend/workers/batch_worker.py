"""Batch worker entrypoint."""

import asyncio

from backend.core.config import get_settings
from backend.db.postgres import create_postgres_engine, create_sessionmaker
from backend.db.redis import RedisClient
from backend.repositories.request_audit_repository import RequestAuditRepository
from backend.services.batch.batch_queue import RedisBatchQueue
from backend.services.batch.batch_service import PostgresBatchJobStore
from backend.services.batch.batch_worker import BatchWorker
from backend.services.inference.token_accounting import HeuristicTokenEstimator
from backend.services.inference.usage_finalizer import RequestAuditService
from backend.services.observability.sentry import capture_exception, initialize_sentry
from backend.services.rate_limit.admission import AdmissionService
from backend.services.rate_limit.concurrency_limiter import ConcurrencyLimiter
from backend.services.rate_limit.quota_reserver import QuotaReserver
from backend.services.rate_limit.rate_limiter import RateLimiter
from backend.services.vllm.client import VLLMClient


async def main() -> None:
    settings = get_settings()
    initialize_sentry(settings)
    redis_client = RedisClient.from_url(settings.redis_url)
    engine = create_postgres_engine(settings.database_url)
    sessionmaker = create_sessionmaker(engine)
    vllm_client = VLLMClient(
        settings.vllm_base_url,
        connect_timeout_seconds=settings.vllm_connect_timeout_seconds,
        read_timeout_seconds=settings.vllm_read_timeout_seconds,
    )
    worker = BatchWorker(
        store=PostgresBatchJobStore(sessionmaker),
        queue=RedisBatchQueue(redis_client),
        vllm_client=vllm_client,
        admission_service=AdmissionService(
            rate_limiter=RateLimiter(redis_client),
            concurrency_limiter=ConcurrencyLimiter(redis_client),
            quota_reserver=QuotaReserver(redis_client, tpm_limit=settings.token_limit_tpm),
            rpm_limit=settings.rate_limit_rpm,
            concurrent_request_limit=settings.concurrent_request_limit,
        ),
        token_estimator=HeuristicTokenEstimator(),
        audit_service=RequestAuditService(RequestAuditRepository, sessionmaker),
        settings=settings,
    )
    try:
        while True:
            processed = await worker.process_one()
            if not processed:
                await asyncio.sleep(1.0)
    finally:
        await vllm_client.close()
        await redis_client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        capture_exception(exc, tags={"component": "batch_worker"})
        raise
