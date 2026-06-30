"""Batch job repository."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.batch_job import BatchJob
from backend.utils.time import utc_now


class BatchJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: str,
        project_id: str,
        api_key_id: str,
        model: str,
        input_payload: dict[str, Any],
    ) -> BatchJob:
        job = BatchJob(
            user_id=user_id,
            project_id=project_id,
            api_key_id=api_key_id,
            model=model,
            status="queued",
            request_count=1,
            metadata_json={"input_payload": input_payload},
        )
        self._session.add(job)
        await self._session.flush()
        await self._session.refresh(job)
        return job

    async def get(self, job_id: str) -> BatchJob | None:
        return await self._session.get(BatchJob, job_id)

    async def list_by_status(self, status: str, *, limit: int = 100) -> list[BatchJob]:
        result = await self._session.execute(
            select(BatchJob)
            .where(BatchJob.status == status)
            .order_by(BatchJob.created_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_status(self, job: BatchJob, status: str) -> BatchJob:
        job.status = status
        job.updated_at = utc_now()
        await self._session.flush()
        await self._session.refresh(job)
        return job

    async def mark_succeeded(
        self, job: BatchJob, *, result: dict[str, Any], usage: dict[str, int]
    ) -> BatchJob:
        metadata = dict(job.metadata_json or {})
        metadata["result_payload"] = result
        metadata["usage"] = usage
        metadata["completed_at"] = utc_now().isoformat()
        job.metadata_json = metadata
        job.status = "succeeded"
        job.completed_count = 1
        job.failed_count = 0
        job.error_code = None
        job.error_message = None
        job.updated_at = utc_now()
        await self._session.flush()
        await self._session.refresh(job)
        return job

    async def mark_failed(self, job: BatchJob, *, error_code: str, error_message: str) -> BatchJob:
        metadata = dict(job.metadata_json or {})
        metadata["completed_at"] = utc_now().isoformat()
        job.metadata_json = metadata
        job.status = "failed"
        job.error_code = error_code
        job.error_message = error_message[:1024]
        job.failed_count = 1
        job.updated_at = utc_now()
        await self._session.flush()
        await self._session.refresh(job)
        return job
