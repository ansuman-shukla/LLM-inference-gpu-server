"""Integration tests for rate limiting flow."""

from typing import Any

from fastapi.testclient import TestClient

from backend.core.errors import AppError
from backend.main import create_app
from backend.services.rate_limit.admission import AdmissionService
from backend.services.rate_limit.concurrency_limiter import ConcurrencyLimiter, concurrency_key
from backend.services.rate_limit.quota_reserver import QuotaReserver
from backend.services.rate_limit.rate_limiter import RateLimiter, rpm_key
from tests.conftest import audit_service_for_tests, FakeRedis, auth_headers, auth_service_for_tests


class FakeVLLMClient:
    async def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": "chatcmpl_rate",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
        }


class FailingVLLMClient:
    async def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise AppError(
            message="upstream failed",
            code="upstream_error",
            status_code=502,
            type="server_error",
        )


def _admission_service(
    redis: FakeRedis, *, rpm_limit: int = 10, concurrent_request_limit: int = 10
) -> AdmissionService:
    return AdmissionService(
        rate_limiter=RateLimiter(redis),
        concurrency_limiter=ConcurrencyLimiter(redis),
        quota_reserver=QuotaReserver(),
        rpm_limit=rpm_limit,
        concurrent_request_limit=concurrent_request_limit,
    )


def _post_chat(client: TestClient) -> Any:
    return client.post(
        "/v1/chat/completions",
        json={"model": "test-model", "messages": [{"role": "user", "content": "hello"}]},
        headers=auth_headers(),
    )


def test_exceeding_rpm_returns_429() -> None:
    redis = FakeRedis()
    app = create_app(
        vllm_client=FakeVLLMClient(),
        auth_service=auth_service_for_tests(),
        admission_service=_admission_service(redis, rpm_limit=1),
        audit_service=audit_service_for_tests(),
    )

    with TestClient(app) as client:
        first = _post_chat(client)
        second = _post_chat(client)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limit_exceeded"
    assert redis.values[rpm_key("key_test")] == 2


def test_concurrent_request_limit_returns_429() -> None:
    redis = FakeRedis()
    redis.values[concurrency_key("key_test")] = 1
    app = create_app(
        vllm_client=FakeVLLMClient(),
        auth_service=auth_service_for_tests(),
        admission_service=_admission_service(redis, concurrent_request_limit=1),
        audit_service=audit_service_for_tests(),
    )

    with TestClient(app) as client:
        response = _post_chat(client)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "concurrency_limit_exceeded"
    assert redis.values[concurrency_key("key_test")] == 1


def test_failed_request_does_not_leak_concurrency_counter() -> None:
    redis = FakeRedis()
    app = create_app(
        vllm_client=FailingVLLMClient(),
        auth_service=auth_service_for_tests(),
        admission_service=_admission_service(redis),
        audit_service=audit_service_for_tests(),
    )

    with TestClient(app) as client:
        response = _post_chat(client)

    assert response.status_code == 502
    assert concurrency_key("key_test") not in redis.values


def test_redis_unavailable_returns_503() -> None:
    app = create_app(
        vllm_client=FakeVLLMClient(),
        auth_service=auth_service_for_tests(),
        admission_service=_admission_service(FakeRedis(fail=True)),
        audit_service=audit_service_for_tests(),
    )

    with TestClient(app) as client:
        response = _post_chat(client)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "dependency_unavailable"
