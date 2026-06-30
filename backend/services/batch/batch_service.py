"""Batch service."""

from dataclasses import dataclass, field
from typing import Any, NoReturn, Protocol
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.errors import AppError
from backend.models.batch_job import BatchJob
from backend.repositories.batch_job_repository import BatchJobRepository
from backend.schemas.batch_job import BatchJobCreateRequest, BatchJobResponse
from backend.schemas.chat_completion import ChatCompletionRequest
from backend.services.auth.api_key_service import AuthContext
from backend.utils.time import utc_now

QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"
TERMINAL_STATUSES = {SUCCEEDED, FAILED, CANCELLED}
ALLOWED_TRANSITIONS = {
    QUEUED: {RUNNING, CANCELLED, FAILED},
    RUNNING: {SUCCEEDED, FAILED, CANCELLED},
    SUCCEEDED: set(),
    FAILED: set(),
    CANCELLED: set(),
}


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())


@dataclass
class BatchJobRecord:
    id: str
    user_id: str
    project_id: str
    api_key_id: str
    model: str
    status: str
    input_payload: dict[str, Any]
    result_payload: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    request_count: int = 1
    completed_count: int = 0
    failed_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_response(self) -> BatchJobResponse:
        return BatchJobResponse(
            job_id=self.id,
            status=self.status,  # type: ignore[arg-type]
            model=self.model,
            request_count=self.request_count,
            completed_count=self.completed_count,
            failed_count=self.failed_count,
            result=self.result_payload,
            error_code=self.error_code,
            error_message=self.error_message,
        )


class BatchJobStore(Protocol):
    async def create(
        self, *, auth_context: AuthContext, payload: dict[str, Any], model: str
    ) -> BatchJobRecord: ...

    async def get(self, job_id: str) -> BatchJobRecord | None: ...

    async def transition(self, job_id: str, target_status: str) -> BatchJobRecord | None: ...

    async def mark_succeeded(
        self, job_id: str, *, result: dict[str, Any], usage: dict[str, int]
    ) -> BatchJobRecord | None: ...

    async def mark_failed(
        self, job_id: str, *, error_code: str, error_message: str
    ) -> BatchJobRecord | None: ...

    async def list_recoverable(self, *, limit: int = 100) -> list[BatchJobRecord]: ...


class BatchQueue(Protocol):
    async def enqueue(self, job_id: str) -> None: ...

    async def dequeue(self) -> str | None: ...

    async def contains(self, job_id: str) -> bool: ...


class BatchJobService:
    def __init__(self, *, store: BatchJobStore, queue: BatchQueue) -> None:
        self.store = store
        self.queue = queue

    async def submit(
        self, *, auth_context: AuthContext, request_body: BatchJobCreateRequest
    ) -> BatchJobRecord:
        payload = request_body.model_dump(exclude_none=True)
        if payload.get("stream") is True:
            raise AppError(
                message="Batch jobs do not support streaming requests",
                code="batch_streaming_not_supported",
                status_code=400,
                type="invalid_request_error",
                param="stream",
            )
        payload["stream"] = False
        job = await self.store.create(
            auth_context=auth_context, payload=payload, model=request_body.model
        )
        try:
            await self.queue.enqueue(job.id)
        except Exception:
            # Postgres remains the source of truth; recovery scanner can re-enqueue.
            return job
        return job

    async def get(self, job_id: str, *, auth_context: AuthContext | None = None) -> BatchJobRecord:
        job = await self.store.get(job_id)
        if job is None:
            _raise_batch_job_not_found()
        if auth_context is not None and not _can_access_job(job, auth_context):
            _raise_batch_job_not_found()
        return job

    async def cancel(
        self, job_id: str, *, auth_context: AuthContext | None = None
    ) -> BatchJobRecord:
        job = await self.get(job_id, auth_context=auth_context)
        if job.status in TERMINAL_STATUSES:
            return job
        cancelled = await self.store.transition(job_id, CANCELLED)
        if (
            cancelled is not None
            and auth_context is not None
            and not _can_access_job(cancelled, auth_context)
        ):
            _raise_batch_job_not_found()
        return cancelled or await self.get(job_id, auth_context=auth_context)


class InMemoryBatchJobStore:
    def __init__(self) -> None:
        self.jobs: dict[str, BatchJobRecord] = {}

    async def create(
        self, *, auth_context: AuthContext, payload: dict[str, Any], model: str
    ) -> BatchJobRecord:
        job = BatchJobRecord(
            id=f"job_{uuid4().hex}",
            user_id=auth_context.user_id,
            project_id=auth_context.project_id,
            api_key_id=auth_context.api_key_id,
            model=model,
            status=QUEUED,
            input_payload=payload,
        )
        self.jobs[job.id] = job
        return job

    async def get(self, job_id: str) -> BatchJobRecord | None:
        return self.jobs.get(job_id)

    async def transition(self, job_id: str, target_status: str) -> BatchJobRecord | None:
        job = self.jobs.get(job_id)
        if job is None or not can_transition(job.status, target_status):
            return None
        job.status = target_status
        return job

    async def mark_succeeded(
        self, job_id: str, *, result: dict[str, Any], usage: dict[str, int]
    ) -> BatchJobRecord | None:
        job = self.jobs.get(job_id)
        if job is None or job.status == CANCELLED:
            return None
        job.status = SUCCEEDED
        job.result_payload = result
        job.completed_count = 1
        job.failed_count = 0
        job.metadata["usage"] = usage
        return job

    async def mark_failed(
        self, job_id: str, *, error_code: str, error_message: str
    ) -> BatchJobRecord | None:
        job = self.jobs.get(job_id)
        if job is None or job.status == CANCELLED:
            return None
        job.status = FAILED
        job.error_code = error_code
        job.error_message = error_message
        job.failed_count = 1
        return job

    async def list_recoverable(self, *, limit: int = 100) -> list[BatchJobRecord]:
        return [job for job in self.jobs.values() if job.status == QUEUED][:limit]


class PostgresBatchJobStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create(
        self, *, auth_context: AuthContext, payload: dict[str, Any], model: str
    ) -> BatchJobRecord:
        async with self._sessionmaker.begin() as session:
            repository = BatchJobRepository(session)
            model_obj = await repository.create(
                user_id=auth_context.user_id,
                project_id=auth_context.project_id,
                api_key_id=auth_context.api_key_id,
                model=model,
                input_payload=payload,
            )
            return _record_from_model(model_obj)

    async def get(self, job_id: str) -> BatchJobRecord | None:
        async with self._sessionmaker.begin() as session:
            model_obj = await BatchJobRepository(session).get(job_id)
            return _record_from_model(model_obj) if model_obj is not None else None

    async def transition(self, job_id: str, target_status: str) -> BatchJobRecord | None:
        async with self._sessionmaker.begin() as session:
            repository = BatchJobRepository(session)
            model_obj = await repository.get(job_id)
            if model_obj is None or not can_transition(model_obj.status, target_status):
                return None
            model_obj = await repository.update_status(model_obj, target_status)
            return _record_from_model(model_obj)

    async def mark_succeeded(
        self, job_id: str, *, result: dict[str, Any], usage: dict[str, int]
    ) -> BatchJobRecord | None:
        async with self._sessionmaker.begin() as session:
            repository = BatchJobRepository(session)
            model_obj = await repository.get(job_id)
            if model_obj is None or model_obj.status == CANCELLED:
                return None
            model_obj = await repository.mark_succeeded(model_obj, result=result, usage=usage)
            return _record_from_model(model_obj)

    async def mark_failed(
        self, job_id: str, *, error_code: str, error_message: str
    ) -> BatchJobRecord | None:
        async with self._sessionmaker.begin() as session:
            repository = BatchJobRepository(session)
            model_obj = await repository.get(job_id)
            if model_obj is None or model_obj.status == CANCELLED:
                return None
            model_obj = await repository.mark_failed(
                model_obj, error_code=error_code, error_message=error_message
            )
            return _record_from_model(model_obj)

    async def list_recoverable(self, *, limit: int = 100) -> list[BatchJobRecord]:
        async with self._sessionmaker.begin() as session:
            rows = await BatchJobRepository(session).list_by_status(QUEUED, limit=limit)
            return [_record_from_model(row) for row in rows]


def _record_from_model(model_obj: BatchJob) -> BatchJobRecord:
    metadata = dict(model_obj.metadata_json or {})
    raw_input_payload = metadata.get("input_payload")
    input_payload = raw_input_payload if isinstance(raw_input_payload, dict) else {}
    raw_result_payload = metadata.get("result_payload")
    result_payload = raw_result_payload if isinstance(raw_result_payload, dict) else None
    return BatchJobRecord(
        id=model_obj.id,
        user_id=model_obj.user_id,
        project_id=model_obj.project_id,
        api_key_id=model_obj.api_key_id,
        model=model_obj.model,
        status=model_obj.status,
        input_payload=input_payload,
        result_payload=result_payload,
        error_code=model_obj.error_code,
        error_message=model_obj.error_message,
        request_count=model_obj.request_count,
        completed_count=model_obj.completed_count,
        failed_count=model_obj.failed_count,
        metadata=metadata,
    )


def _can_access_job(job: BatchJobRecord, auth_context: AuthContext) -> bool:
    return job.user_id == auth_context.user_id and job.project_id == auth_context.project_id


def _raise_batch_job_not_found() -> NoReturn:
    raise AppError(
        message="Batch job not found",
        code="batch_job_not_found",
        status_code=404,
        type="invalid_request_error",
    )


def chat_request_from_batch(job: BatchJobRecord) -> ChatCompletionRequest:
    return ChatCompletionRequest.model_validate(job.input_payload)


def usage_dict(prompt_tokens: int, completion_tokens: int, total_tokens: int) -> dict[str, int]:
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def utc_timestamp() -> str:
    return utc_now().isoformat()
