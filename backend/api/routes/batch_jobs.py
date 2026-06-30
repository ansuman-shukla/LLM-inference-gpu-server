"""Batch job routes."""

from fastapi import APIRouter, Request

from backend.core.config import Settings
from backend.core.errors import AppError
from backend.db.postgres import create_postgres_engine, create_sessionmaker
from backend.db.redis import RedisClient
from backend.schemas.batch_job import (
    BatchJobCreateRequest,
    BatchJobResponse,
    BatchJobSubmitResponse,
)
from backend.services.auth.api_key_service import AuthContext, ensure_model_allowed
from backend.services.batch.batch_queue import RedisBatchQueue
from backend.services.batch.batch_service import BatchJobService, PostgresBatchJobStore

router = APIRouter(prefix="/v1/batch/jobs", tags=["batch_jobs"])


@router.post("", response_model=BatchJobSubmitResponse)
async def submit_batch_job(
    request_body: BatchJobCreateRequest, request: Request
) -> BatchJobSubmitResponse:
    auth_context = _auth_context(request)
    ensure_model_allowed(auth_context, request_body.model)
    service = _get_or_create_batch_service(request)
    job = await service.submit(auth_context=auth_context, request_body=request_body)
    return BatchJobSubmitResponse(job_id=job.id, status=job.status)  # type: ignore[arg-type]


@router.get("/{job_id}", response_model=BatchJobResponse)
async def get_batch_job(job_id: str, request: Request) -> BatchJobResponse:
    auth_context = _auth_context(request)
    job = await _get_or_create_batch_service(request).get(job_id, auth_context=auth_context)
    return job.to_response()


@router.post("/{job_id}/cancel", response_model=BatchJobResponse)
async def cancel_batch_job(job_id: str, request: Request) -> BatchJobResponse:
    auth_context = _auth_context(request)
    job = await _get_or_create_batch_service(request).cancel(job_id, auth_context=auth_context)
    return job.to_response()


def _auth_context(request: Request) -> AuthContext:
    auth_context = getattr(request.state, "auth_context", None)
    if not isinstance(auth_context, AuthContext):
        raise AppError(
            message="Missing API key",
            code="missing_api_key",
            status_code=401,
            type="invalid_request_error",
        )
    return auth_context


def _get_or_create_batch_service(request: Request) -> BatchJobService:
    service = getattr(request.app.state, "batch_service", None)
    if service is not None:
        return service

    settings: Settings = request.app.state.settings
    engine = getattr(request.app.state, "postgres_engine", None)
    if engine is None:
        engine = create_postgres_engine(settings.database_url)
        request.app.state.postgres_engine = engine
    redis_client = getattr(request.app.state, "redis_client", None)
    if redis_client is None:
        redis_client = RedisClient.from_url(settings.redis_url)
        request.app.state.redis_client = redis_client
    service = BatchJobService(
        store=PostgresBatchJobStore(create_sessionmaker(engine)),
        queue=RedisBatchQueue(redis_client),
    )
    request.app.state.batch_service = service
    return service
