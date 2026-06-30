"""Chat completion routes."""

from collections.abc import AsyncIterator
from time import perf_counter
from typing import Any, Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.core.config import Settings
from backend.core.constants import REQUEST_ID_HEADER
from backend.core.errors import AppError
from backend.services.analytics.event_collector import AnalyticsCollector
from backend.services.analytics.event_models import UsageEvent
from backend.db.postgres import create_postgres_engine, create_sessionmaker
from backend.db.redis import RedisClient
from backend.schemas.chat_completion import ChatCompletionRequest
from backend.services.auth.api_key_service import AuthContext, ensure_model_allowed
from backend.repositories.request_audit_repository import RequestAuditRepository
from backend.services.inference.request_lifecycle import (
    build_audit_final,
    build_audit_start,
)
from backend.services.inference.token_accounting import (
    HeuristicTokenEstimator,
    TokenEstimator,
    TokenPlan,
    UsageRecord,
    build_token_plan,
    stream_delta_text,
    usage_from_response,
    usage_from_stream_text,
)
from backend.services.inference.usage_finalizer import RequestAuditService
from backend.services.observability.metrics import (
    record_stream_finished,
    record_stream_started,
    record_stream_ttft,
)
from backend.services.observability.sentry import bind_request_context, capture_request_exception
from backend.services.rate_limit.admission import AdmissionLease, AdmissionService
from backend.services.rate_limit.concurrency_limiter import ConcurrencyLimiter
from backend.services.rate_limit.quota_reserver import QuotaReserver
from backend.services.rate_limit.rate_limiter import RateLimiter
from backend.services.vllm.payload_mapper import normalize_chat_completion_payload
from backend.utils.time import utc_now
from backend.services.vllm.stream import (
    DONE_LINE,
    SSE_HEADERS,
    SSE_MEDIA_TYPE,
    ensure_done_event,
    stream_with_heartbeats,
)

router = APIRouter(prefix="/v1", tags=["chat"])


class AnalyticsCollectorController(Protocol):
    def collect(self, event: Any) -> bool: ...


class RequestAuditController(Protocol):
    async def start(self, audit: Any) -> str: ...

    async def finalize(self, final: Any) -> None: ...


class AdmissionController(Protocol):
    async def admit(
        self, auth_context: AuthContext, *, estimated_tokens: int = 0
    ) -> AdmissionLease: ...


class ChatCompletionClient(Protocol):
    async def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def stream_chat_completion(self, payload: dict[str, Any]) -> AsyncIterator[str]: ...


@router.post("/chat/completions", response_model=None)
async def create_chat_completion(
    request_body: ChatCompletionRequest,
    request: Request,
) -> JSONResponse | StreamingResponse:
    """Proxy OpenAI-compatible chat completions to vLLM."""
    auth_context = getattr(request.state, "auth_context", None)
    if not isinstance(auth_context, AuthContext):
        raise AppError(
            message="Missing API key",
            code="missing_api_key",
            status_code=401,
            type="invalid_request_error",
        )
    ensure_model_allowed(auth_context, request_body.model)

    token_estimator = _get_or_create_token_estimator(request)
    settings: Settings = request.app.state.settings
    token_plan = build_token_plan(
        request_body,
        token_estimator,
        max_input_tokens=settings.max_input_tokens,
        max_output_tokens=settings.max_output_tokens,
        max_total_tokens=settings.max_total_tokens,
    )
    admission_service = _get_or_create_admission_service(request)
    admission_lease = await admission_service.admit(
        auth_context, estimated_tokens=token_plan.estimated_total_tokens
    )
    payload = normalize_chat_completion_payload(request_body)
    request_id = getattr(request.state, "request_id", None)
    bind_request_context(request, model=request_body.model, stream=request_body.stream)
    audit_service = _get_or_create_audit_service(request)
    audit_record_id = await audit_service.start(
        build_audit_start(
            request_id=str(request_id or ""),
            auth_context=auth_context,
            model=request_body.model,
            messages=request_body.messages,
        )
    )
    audit_started_at = perf_counter()
    headers = {REQUEST_ID_HEADER: request_id} if request_id is not None else None
    client: ChatCompletionClient = request.app.state.vllm_client

    if request_body.stream:
        return StreamingResponse(
            _stream_response(
                client,
                payload,
                request,
                admission_lease,
                token_plan,
                token_estimator,
                audit_service,
                audit_record_id,
                audit_started_at,
                auth_context,
                str(request_id or ""),
                request_body.model,
            ),
            media_type=SSE_MEDIA_TYPE,
            headers={**SSE_HEADERS, **(headers or {})},
        )

    try:
        response = await client.create_chat_completion(payload)
        usage = usage_from_response(response, token_plan, token_estimator)
        await admission_lease.finalize_tokens(actual_tokens=usage.total_tokens)
        _record_usage(request, usage)
        latency_ms = _elapsed_ms(audit_started_at)
        await audit_service.finalize(
            build_audit_final(
                record_id=audit_record_id,
                usage=usage,
                latency_ms=latency_ms,
            )
        )
        _emit_usage_analytics(
            request,
            auth_context=auth_context,
            request_id=str(request_id or ""),
            model=request_body.model,
            usage=usage,
            latency_ms=latency_ms,
            error_code=None,
        )
        return JSONResponse(content=response, headers=headers)
    except Exception as exc:
        capture_request_exception(request, exc, model=request_body.model, stream=False)
        await admission_lease.finalize_tokens(actual_tokens=0, release_all=True)
        failed_usage = UsageRecord(
            prompt_tokens=token_plan.prompt_tokens,
            completion_tokens=0,
            total_tokens=0,
            status="failed",
        )
        _record_usage(request, failed_usage)
        latency_ms = _elapsed_ms(audit_started_at)
        error_code = getattr(exc, "code", "internal_server_error")
        await audit_service.finalize(
            build_audit_final(
                record_id=audit_record_id,
                usage=failed_usage,
                latency_ms=latency_ms,
                error_code=error_code,
            )
        )
        _emit_usage_analytics(
            request,
            auth_context=auth_context,
            request_id=str(request_id or ""),
            model=request_body.model,
            usage=failed_usage,
            latency_ms=latency_ms,
            error_code=error_code,
        )
        raise
    finally:
        await admission_lease.release()


async def _stream_response(
    client: ChatCompletionClient,
    payload: dict[str, Any],
    request: Request,
    admission_lease: AdmissionLease | None = None,
    token_plan: TokenPlan | None = None,
    token_estimator: TokenEstimator | None = None,
    audit_service: RequestAuditController | None = None,
    audit_record_id: str | None = None,
    audit_started_at: float | None = None,
    auth_context: AuthContext | None = None,
    request_id: str | None = None,
    model: str | None = None,
) -> AsyncIterator[str]:
    started_at = perf_counter()
    first_token_seen = False
    record_stream_started()
    upstream_stream = client.stream_chat_completion(payload)
    heartbeat_stream = stream_with_heartbeats(upstream_stream)
    event_stream = ensure_done_event(heartbeat_stream)
    completion_text = ""
    status = "completed"
    error_code: str | None = None
    try:
        async for event in event_stream:
            if await request.is_disconnected():
                status = "client_disconnected"
                break
            completion_text += stream_delta_text(event)
            if not first_token_seen and event.startswith("data: ") and event.strip() != DONE_LINE:
                ttft_seconds = perf_counter() - started_at
                ttft_ms = int(ttft_seconds * 1000)
                request.state.ttft_ms = ttft_ms
                request.app.state.last_stream_ttft_ms = ttft_ms
                record_stream_ttft(model=model, ttft_seconds=ttft_seconds)
                first_token_seen = True
            yield event
    except Exception as exc:
        status = "failed"
        error_code = getattr(exc, "code", "internal_server_error")
        capture_request_exception(request, exc, model=model, stream=True)
        raise
    finally:
        await _close_async_iterator(event_stream)
        await _close_async_iterator(heartbeat_stream)
        await _close_async_iterator(upstream_stream)
        if admission_lease is not None and token_plan is not None and token_estimator is not None:
            usage = usage_from_stream_text(
                completion_text,
                token_plan,
                token_estimator,
                status=status,
            )
            await admission_lease.finalize_tokens(
                actual_tokens=usage.total_tokens,
                release_all=status == "failed",
            )
            _record_usage(request, usage)
            if audit_service is not None and audit_record_id is not None:
                latency_ms = _elapsed_ms(audit_started_at)
                await audit_service.finalize(
                    build_audit_final(
                        record_id=audit_record_id,
                        usage=usage,
                        latency_ms=latency_ms,
                        error_code=error_code,
                    )
                )
                if auth_context is not None and request_id is not None and model is not None:
                    _emit_usage_analytics(
                        request,
                        auth_context=auth_context,
                        request_id=request_id,
                        model=model,
                        usage=usage,
                        latency_ms=latency_ms,
                        error_code=error_code,
                    )
        if admission_lease is not None:
            await admission_lease.release()
        record_stream_finished()


async def _close_async_iterator(iterator: AsyncIterator[str]) -> None:
    aclose = getattr(iterator, "aclose", None)
    if aclose is not None:
        await aclose()


def _get_or_create_admission_service(request: Request) -> AdmissionController:
    admission_service = getattr(request.app.state, "admission_service", None)
    if admission_service is not None:
        return admission_service

    settings: Settings = request.app.state.settings
    redis_client = RedisClient.from_url(settings.redis_url)
    request.app.state.redis_client = redis_client
    admission_service = AdmissionService(
        rate_limiter=RateLimiter(redis_client),
        concurrency_limiter=ConcurrencyLimiter(redis_client),
        quota_reserver=QuotaReserver(redis_client, tpm_limit=settings.token_limit_tpm),
        rpm_limit=settings.rate_limit_rpm,
        concurrent_request_limit=settings.concurrent_request_limit,
    )
    request.app.state.admission_service = admission_service
    return admission_service


def _get_or_create_token_estimator(request: Request) -> TokenEstimator:
    token_estimator = getattr(request.app.state, "token_estimator", None)
    if token_estimator is not None:
        return token_estimator
    token_estimator = HeuristicTokenEstimator()
    request.app.state.token_estimator = token_estimator
    return token_estimator


def _record_usage(request: Request, usage: UsageRecord) -> None:
    request.state.usage = usage
    request.app.state.last_usage = usage
    usage_records = getattr(request.app.state, "usage_records", None)
    if usage_records is None:
        usage_records = []
        request.app.state.usage_records = usage_records
    usage_records.append(usage)


def _get_or_create_audit_service(request: Request) -> RequestAuditController:
    audit_service = getattr(request.app.state, "audit_service", None)
    if audit_service is not None:
        return audit_service

    settings: Settings = request.app.state.settings
    engine = getattr(request.app.state, "postgres_engine", None)
    if engine is None:
        engine = create_postgres_engine(settings.database_url)
        request.app.state.postgres_engine = engine
    audit_service = RequestAuditService(
        RequestAuditRepository,
        create_sessionmaker(engine),
    )
    request.app.state.audit_service = audit_service
    return audit_service


def _elapsed_ms(started_at: float | None) -> int | None:
    if started_at is None:
        return None
    return int((perf_counter() - started_at) * 1000)


def _get_or_create_analytics_collector(request: Request) -> AnalyticsCollectorController:
    collector = getattr(request.app.state, "analytics_collector", None)
    if collector is not None:
        return collector
    settings: Settings = request.app.state.settings
    collector = AnalyticsCollector(max_size=settings.analytics_queue_size)
    request.app.state.analytics_collector = collector
    return collector


def _emit_usage_analytics(
    request: Request,
    *,
    auth_context: AuthContext,
    request_id: str,
    model: str,
    usage: UsageRecord,
    latency_ms: int | None,
    error_code: str | None,
) -> None:
    try:
        collector = _get_or_create_analytics_collector(request)
        collector.collect(
            UsageEvent(
                event_time=utc_now(),
                request_id=request_id,
                user_id=auth_context.user_id,
                project_id=auth_context.project_id,
                api_key_id=auth_context.api_key_id,
                model=model,
                status=usage.status,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                latency_ms=latency_ms,
                error_code=error_code,
                critical=False,
            )
        )
    except Exception:
        # Analytics must never raise into the request path.
        return
