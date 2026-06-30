"""Integration tests for token accounting flow."""

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from backend.api.routes.chat_completions import _stream_response
from backend.main import create_app
from backend.schemas.chat_completion import ChatCompletionRequest
from backend.services.inference.token_accounting import build_token_plan
from backend.services.rate_limit.admission import AdmissionService
from backend.services.rate_limit.concurrency_limiter import ConcurrencyLimiter
from backend.services.rate_limit.quota_reserver import QuotaReserver
from backend.services.rate_limit.rate_limiter import RateLimiter, tpm_key
from tests.conftest import audit_service_for_tests, FakeRedis, auth_headers, auth_service_for_tests


class OneTokenEstimator:
    def count_text(self, text: str) -> int:
        return 1 if text else 0


class FakeUsageVLLMClient:
    async def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": "chatcmpl_usage",
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


def _admission_service(redis: FakeRedis) -> AdmissionService:
    return AdmissionService(
        rate_limiter=RateLimiter(redis),
        concurrency_limiter=ConcurrencyLimiter(redis),
        quota_reserver=QuotaReserver(redis, tpm_limit=100),
        rpm_limit=10,
        concurrent_request_limit=10,
    )


def test_completed_request_writes_correct_usage() -> None:
    redis = FakeRedis()
    estimator = OneTokenEstimator()
    app = create_app(
        vllm_client=FakeUsageVLLMClient(),
        auth_service=auth_service_for_tests(),
        admission_service=_admission_service(redis),
        audit_service=audit_service_for_tests(),
        token_estimator=estimator,
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

    assert response.status_code == 200
    assert app.state.last_usage.prompt_tokens == 3
    assert app.state.last_usage.completion_tokens == 4
    assert app.state.last_usage.total_tokens == 7
    assert app.state.last_usage.status == "completed"
    assert redis.values[tpm_key("key_test")] == 7


def test_disconnected_streaming_request_writes_partial_usage() -> None:
    class FakeStreamingClient:
        async def stream_chat_completion(self, payload: dict[str, Any]) -> AsyncIterator[str]:
            yield 'data: {"choices":[{"delta":{"content":"hel"}}]}'
            yield 'data: {"choices":[{"delta":{"content":"lo"}}]}'

    class DisconnectingRequest:
        def __init__(self) -> None:
            self.calls = 0
            self.state = SimpleNamespace()
            self.app = SimpleNamespace(state=SimpleNamespace())

        async def is_disconnected(self) -> bool:
            self.calls += 1
            return self.calls > 1

    class RecordingLease:
        def __init__(self) -> None:
            self.actual_tokens: int | None = None
            self.release_all: bool | None = None
            self.released = False

        async def finalize_tokens(self, *, actual_tokens: int, release_all: bool = False) -> None:
            self.actual_tokens = actual_tokens
            self.release_all = release_all

        async def release(self) -> None:
            self.released = True

    async def scenario() -> tuple[RecordingLease, Any]:
        request = DisconnectingRequest()
        estimator = OneTokenEstimator()
        token_plan = build_token_plan(
            ChatCompletionRequest(
                model="test-model",
                messages=[{"role": "user", "content": "hello"}],
                max_tokens=10,
            ),
            estimator,
            max_input_tokens=100,
            max_output_tokens=20,
            max_total_tokens=120,
        )
        lease = RecordingLease()
        stream = _stream_response(
            FakeStreamingClient(),
            {"stream": True},
            request,
            lease,
            token_plan,
            estimator,
        )
        assert await anext(stream) == 'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n'
        try:
            await anext(stream)
        except StopAsyncIteration:
            pass
        return lease, request.app.state.last_usage

    lease, usage = asyncio.run(scenario())

    assert usage.status == "client_disconnected"
    assert usage.completion_tokens == 1
    assert lease.release_all is False
    assert lease.actual_tokens == usage.total_tokens
    assert lease.released is True
