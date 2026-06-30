"""Batch worker service."""

from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any, Protocol

from backend.core.config import Settings
from backend.services.analytics.event_models import UsageEvent
from backend.services.auth.api_key_service import AuthContext
from backend.services.batch.batch_service import (
    CANCELLED,
    RUNNING,
    BatchJobStore,
    BatchQueue,
    chat_request_from_batch,
    usage_dict,
)
from backend.services.inference.request_lifecycle import build_audit_final, build_audit_start
from backend.services.inference.token_accounting import (
    TokenEstimator,
    UsageRecord,
    build_token_plan,
    usage_from_response,
)
from backend.services.observability.sentry import capture_exception
from backend.services.vllm.payload_mapper import normalize_chat_completion_payload
from backend.utils.ids import generate_request_id
from backend.utils.time import utc_now


class BatchVLLMClient(Protocol):
    async def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class AdmissionController(Protocol):
    async def admit(self, auth_context: AuthContext, *, estimated_tokens: int = 0) -> Any: ...


class RequestAuditController(Protocol):
    async def start(self, audit: Any) -> str: ...

    async def finalize(self, final: Any) -> None: ...


class AnalyticsCollectorController(Protocol):
    def collect(self, event: Any) -> bool: ...


class BatchWorker:
    def __init__(
        self,
        *,
        store: BatchJobStore,
        queue: BatchQueue,
        vllm_client: BatchVLLMClient,
        admission_service: AdmissionController,
        token_estimator: TokenEstimator,
        audit_service: RequestAuditController,
        settings: Settings,
        analytics_collector: AnalyticsCollectorController | None = None,
        should_run_job: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        self.store = store
        self.queue = queue
        self.vllm_client = vllm_client
        self.admission_service = admission_service
        self.token_estimator = token_estimator
        self.audit_service = audit_service
        self.settings = settings
        self.analytics_collector = analytics_collector
        self.should_run_job = should_run_job

    async def process_one(self) -> bool:
        job_id = await self.queue.dequeue()
        if job_id is None:
            return False

        job = await self.store.get(job_id)
        if job is None or job.status == CANCELLED:
            return False

        if self.should_run_job is not None and not await self.should_run_job():
            await self.queue.enqueue(job_id)
            return False

        running = await self.store.transition(job_id, RUNNING)
        if running is None:
            return False

        request_id = generate_request_id()
        auth_context = AuthContext(
            api_key_id=running.api_key_id,
            user_id=running.user_id,
            project_id=running.project_id,
            allowed_models=None,
        )
        audit_record_id: str | None = None
        started_at = perf_counter()
        admission_lease: Any | None = None
        try:
            request_body = chat_request_from_batch(running)
            token_plan = build_token_plan(
                request_body,
                self.token_estimator,
                max_input_tokens=self.settings.max_input_tokens,
                max_output_tokens=self.settings.max_output_tokens,
                max_total_tokens=self.settings.max_total_tokens,
            )
            admission_lease = await self.admission_service.admit(
                auth_context, estimated_tokens=token_plan.estimated_total_tokens
            )
            audit_record_id = await self.audit_service.start(
                build_audit_start(
                    request_id=request_id,
                    auth_context=auth_context,
                    model=request_body.model,
                    messages=request_body.messages,
                )
            )
            response = await self.vllm_client.create_chat_completion(
                normalize_chat_completion_payload(request_body)
            )
            usage = usage_from_response(response, token_plan, self.token_estimator)
            await admission_lease.finalize_tokens(actual_tokens=usage.total_tokens)
            latency_ms = _elapsed_ms(started_at)
            await self.audit_service.finalize(
                build_audit_final(record_id=audit_record_id, usage=usage, latency_ms=latency_ms)
            )
            await self.store.mark_succeeded(
                job_id,
                result=response,
                usage=usage_dict(usage.prompt_tokens, usage.completion_tokens, usage.total_tokens),
            )
            self._emit_usage_event(
                auth_context=auth_context,
                request_id=request_id,
                model=request_body.model,
                usage=usage,
                latency_ms=latency_ms,
                error_code=None,
            )
            return True
        except Exception as exc:
            capture_exception(
                exc,
                tags={
                    "component": "batch_worker",
                    "batch_job_id": job_id,
                    "error_code": getattr(exc, "code", "batch_job_failed"),
                },
            )
            error_code = getattr(exc, "code", "batch_job_failed")
            if admission_lease is not None:
                await admission_lease.finalize_tokens(actual_tokens=0, release_all=True)
            failed_usage = UsageRecord(
                prompt_tokens=0, completion_tokens=0, total_tokens=0, status="failed"
            )
            if audit_record_id is not None:
                await self.audit_service.finalize(
                    build_audit_final(
                        record_id=audit_record_id,
                        usage=failed_usage,
                        latency_ms=_elapsed_ms(started_at),
                        error_code=error_code,
                    )
                )
            await self.store.mark_failed(job_id, error_code=error_code, error_message=str(exc))
            return True
        finally:
            if admission_lease is not None:
                await admission_lease.release()

    def _emit_usage_event(
        self,
        *,
        auth_context: AuthContext,
        request_id: str,
        model: str,
        usage: UsageRecord,
        latency_ms: int | None,
        error_code: str | None,
    ) -> None:
        if self.analytics_collector is None:
            return
        try:
            self.analytics_collector.collect(
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
            return


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)
