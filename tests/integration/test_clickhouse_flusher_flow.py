"""Integration tests for ClickHouse flusher flow."""

import asyncio
from typing import Any

from fastapi.testclient import TestClient

from backend.main import create_app
from backend.services.analytics.clickhouse_flusher import ClickHouseFlusher
from backend.services.analytics.event_collector import AnalyticsCollector
from backend.services.analytics.event_models import UsageEvent
from backend.services.rate_limit.admission import AdmissionService
from backend.services.rate_limit.concurrency_limiter import ConcurrencyLimiter
from backend.services.rate_limit.quota_reserver import QuotaReserver
from backend.services.rate_limit.rate_limiter import RateLimiter
from tests.conftest import (
    FakeRedis,
    audit_service_for_tests,
    auth_headers,
    auth_service_for_tests,
)


class FakeVLLMClient:
    async def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": "chatcmpl_analytics",
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


class FakeClickHouseClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.inserts: list[tuple[str, list[tuple[object, ...]], list[str]]] = []

    def insert(self, table: str, rows: list[tuple[object, ...]], column_names: list[str]) -> None:
        if self.fail:
            raise RuntimeError("clickhouse down")
        self.inserts.append((table, rows, column_names))


def _admission_service(redis: FakeRedis) -> AdmissionService:
    return AdmissionService(
        rate_limiter=RateLimiter(redis),
        concurrency_limiter=ConcurrencyLimiter(redis),
        quota_reserver=QuotaReserver(redis, tpm_limit=100),
        rpm_limit=10,
        concurrent_request_limit=10,
    )


def test_successful_request_queues_analytics_event() -> None:
    collector = AnalyticsCollector(max_size=10)
    app = create_app(
        vllm_client=FakeVLLMClient(),
        auth_service=auth_service_for_tests(),
        admission_service=_admission_service(FakeRedis()),
        audit_service=audit_service_for_tests(),
        analytics_collector=collector,
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
    events = collector.drain_batch(10)
    assert len(events) == 1
    assert isinstance(events[0], UsageEvent)
    assert events[0].total_tokens == 7


def test_flusher_writes_batch_to_fake_clickhouse() -> None:
    collector = AnalyticsCollector(max_size=10)
    app = create_app(
        vllm_client=FakeVLLMClient(),
        auth_service=auth_service_for_tests(),
        admission_service=_admission_service(FakeRedis()),
        audit_service=audit_service_for_tests(),
        analytics_collector=collector,
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

    fake_clickhouse = FakeClickHouseClient()
    flusher = ClickHouseFlusher(collector=collector, client=fake_clickhouse, batch_size=10)

    assert asyncio.run(flusher.flush_once()) is True
    assert fake_clickhouse.inserts[0][0] == "usage_events"
    assert len(fake_clickhouse.inserts[0][1]) == 1


def test_clickhouse_down_does_not_break_inference_endpoint() -> None:
    class RaisingCollector:
        def collect(self, event: object) -> bool:
            raise RuntimeError("clickhouse down")

    app = create_app(
        vllm_client=FakeVLLMClient(),
        auth_service=auth_service_for_tests(),
        admission_service=_admission_service(FakeRedis()),
        audit_service=audit_service_for_tests(),
        analytics_collector=RaisingCollector(),
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
    assert response.json()["choices"][0]["message"]["content"] == "ok"
