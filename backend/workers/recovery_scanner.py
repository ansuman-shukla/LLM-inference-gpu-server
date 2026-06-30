"""Recovery scanner worker entrypoint."""

import asyncio

from backend.core.config import get_settings
from backend.db.postgres import create_postgres_engine, create_sessionmaker
from backend.db.redis import RedisClient
from backend.services.batch.batch_queue import RedisBatchQueue
from backend.services.batch.batch_service import PostgresBatchJobStore
from backend.services.batch.recovery_scanner import BatchRecoveryScanner
from backend.services.observability.sentry import capture_exception, initialize_sentry


async def main() -> None:
    settings = get_settings()
    initialize_sentry(settings)
    redis_client = RedisClient.from_url(settings.redis_url)
    engine = create_postgres_engine(settings.database_url)
    scanner = BatchRecoveryScanner(
        store=PostgresBatchJobStore(create_sessionmaker(engine)),
        queue=RedisBatchQueue(redis_client),
    )
    try:
        while True:
            await scanner.reenqueue_missing()
            await asyncio.sleep(5.0)
    finally:
        await redis_client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        capture_exception(exc, tags={"component": "batch_recovery_scanner"})
        raise
