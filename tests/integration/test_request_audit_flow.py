"""Integration tests for request audit flow."""

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from backend.api.routes.chat_completions import _stream_response
from backend.core.errors import AppError
from backend.main import create_app
from backend.schemas.chat_completion import ChatCompletionRequest
from backend.services.inference.request_lifecycle import build_audit_start
from backend.services.inference.token_accounting import build_token_plan
from backend.services.inference.usage_finalizer import InMemoryRequestAuditService
from backend.services.rate_limit.admission import AdmissionService
from backend.services.rate_limit.concurrency_limiter import ConcurrencyLimiter
from backend.services.rate_limit.quota_reserver import QuotaReserver
from backend.services.rate_limit.rate_limiter import RateLimiter
from tests.conftest import FakeRedis, auth_headers, auth_service_for_tests


class OneTokenEstimator:
    def count_text(self, text: str) -> int:
        return 1 if text else 0


class SuccessfulVLLMClient:
    async def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": "chatcmpl_audit",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        }


class TimeoutVLLMClient:
    async def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise AppError(
            message="vLLM upstream timed out",
            code="upstream_timeout",
            status_code=504,
            type="server_error",
        )


def _admission_service(redis: FakeRedis) -> AdmissionService:
    return AdmissionService(
        rate_limiter=RateLimiter(redis),
        concurrency_limiter=ConcurrencyLimiter(redis),
        quota_reserver=QuotaReserver(redis, tpm_limit=100),
        rpm_limit=10,
        concurrent_request_limit=10,
    )


def test_success_creates_final_audit_record() -> None:
    audit_service = InMemoryRequestAuditService()
    app = create_app(
        vllm_client=SuccessfulVLLMClient(),
        auth_service=auth_service_for_tests(),
        admission_service=_admission_service(FakeRedis()),
        token_estimator=OneTokenEstimator(),
        audit_service=audit_service,
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "secret prompt"}],
                "max_tokens": 10,
            },
            headers=auth_headers(),
        )

    assert response.status_code == 200
    assert len(audit_service.records) == 1
    record = audit_service.records[0]
    assert record.start.prompt_hash is not None
    assert "secret prompt" not in repr(record.start)
    assert record.final is not None
    assert record.final.status == "completed"
    assert record.final.total_tokens == 7


def test_upstream_timeout_creates_failed_audit_record() -> None:
    audit_service = InMemoryRequestAuditService()
    app = create_app(
        vllm_client=TimeoutVLLMClient(),
        auth_service=auth_service_for_tests(),
        admission_service=_admission_service(FakeRedis()),
        token_estimator=OneTokenEstimator(),
        audit_service=audit_service,
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 10,
            },
            headers=auth_headers(),
        )

    assert response.status_code == 504
    assert audit_service.records[0].final is not None
    assert audit_service.records[0].final.status == "failed"
    assert audit_service.records[0].final.error_code == "upstream_timeout"


def test_client_disconnect_creates_partial_audit_record() -> None:
    class FakeStreamingClient:
        async def stream_chat_completion(self, payload: dict[str, Any]) -> AsyncIterator[str]:
            yield 'data: {"choices":[{"delta":{"content":"hel"}}]}'
            yield 'data: {"choices":[{"delta":{"content":"lo"}}]}'

    class DisconnectingRequest:
        def __init__(self) -> None:
            self.calls = 0
            self.state = SimpleNamespace(request_id="req_stream")
            self.app = SimpleNamespace(state=SimpleNamespace())

        async def is_disconnected(self) -> bool:
            self.calls += 1
            return self.calls > 1

    class NoopLease:
        async def finalize_tokens(self, *, actual_tokens: int, release_all: bool = False) -> None:
            return None

        async def release(self) -> None:
            return None

    async def scenario() -> InMemoryRequestAuditService:
        request = DisconnectingRequest()
        estimator = OneTokenEstimator()
        body = ChatCompletionRequest(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=10,
        )
        token_plan = build_token_plan(
            body,
            estimator,
            max_input_tokens=100,
            max_output_tokens=20,
            max_total_tokens=120,
        )
        audit_service = InMemoryRequestAuditService()
        audit_id = await audit_service.start(
            build_audit_start(
                request_id="req_stream",
                auth_context=auth_service_for_tests()._contexts["an_test_valid"],
                model="test-model",
                messages=body.messages,
            )
        )
        stream = _stream_response(
            FakeStreamingClient(),
            {"stream": True},
            request,
            NoopLease(),
            token_plan,
            estimator,
            audit_service,
            audit_id,
            0.0,
        )
        assert await anext(stream) == 'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n'
        try:
            await anext(stream)
        except StopAsyncIteration:
            pass
        return audit_service

    audit_service = asyncio.run(scenario())

    assert audit_service.records[0].final is not None
    assert audit_service.records[0].final.status == "client_disconnected"
    assert audit_service.records[0].final.completion_tokens == 1
