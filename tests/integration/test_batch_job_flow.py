"""Integration tests for batch job flow."""

from typing import Any

from fastapi.testclient import TestClient

from backend.core.config import Settings
from backend.main import create_app
from backend.services.analytics.event_collector import AnalyticsCollector
from backend.services.batch.batch_queue import InMemoryBatchQueue
from backend.services.batch.batch_service import InMemoryBatchJobStore
from backend.services.batch.batch_service import BatchJobService
from backend.services.batch.batch_worker import BatchWorker
from backend.services.batch.recovery_scanner import BatchRecoveryScanner
from backend.services.inference.token_accounting import HeuristicTokenEstimator
from backend.services.analytics.event_models import UsageEvent
from backend.services.auth.api_key_service import AuthContext, StaticApiKeyAuthService
from tests.conftest import (
    audit_service_for_tests,
    auth_headers,
    auth_service_for_tests,
    noop_admission_service,
)


class FakeVLLMClient:
    async def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": "chatcmpl_batch",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "batch ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        }


def _payload() -> dict[str, Any]:
    return {
        "model": "test-model",
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 8,
    }


def test_submit_job_worker_processes_and_result_is_stored() -> None:
    store = InMemoryBatchJobStore()
    queue = InMemoryBatchQueue()
    service = BatchJobService(store=store, queue=queue)
    audit_service = audit_service_for_tests()
    collector = AnalyticsCollector(max_size=10)
    app = create_app(
        auth_service=auth_service_for_tests(),
        admission_service=noop_admission_service(),
        audit_service=audit_service,
        batch_service=service,
    )

    with TestClient(app) as client:
        submit_response = client.post("/v1/batch/jobs", json=_payload(), headers=auth_headers())

    assert submit_response.status_code == 200
    job_id = submit_response.json()["job_id"]
    assert submit_response.json()["status"] == "queued"

    worker = BatchWorker(
        store=store,
        queue=queue,
        vllm_client=FakeVLLMClient(),
        admission_service=noop_admission_service(),
        token_estimator=HeuristicTokenEstimator(),
        audit_service=audit_service,
        analytics_collector=collector,
        settings=Settings(),
    )

    import asyncio

    assert asyncio.run(worker.process_one()) is True

    with TestClient(app) as client:
        get_response = client.get(f"/v1/batch/jobs/{job_id}", headers=auth_headers())

    assert get_response.status_code == 200
    body = get_response.json()
    assert body["status"] == "succeeded"
    assert body["result"]["choices"][0]["message"]["content"] == "batch ok"
    assert audit_service.records[0].final is not None
    assert audit_service.records[0].final.total_tokens == 7
    events = collector.drain_batch(10)
    assert len(events) == 1
    assert isinstance(events[0], UsageEvent)
    assert events[0].total_tokens == 7


def test_redis_enqueue_failure_leaves_recoverable_postgres_job() -> None:
    store = InMemoryBatchJobStore()
    failing_queue = InMemoryBatchQueue(fail_enqueue=True)
    service = BatchJobService(store=store, queue=failing_queue)
    app = create_app(auth_service=auth_service_for_tests(), batch_service=service)

    with TestClient(app) as client:
        submit_response = client.post("/v1/batch/jobs", json=_payload(), headers=auth_headers())

    assert submit_response.status_code == 200
    job_id = submit_response.json()["job_id"]
    assert store.jobs[job_id].status == "queued"

    recovery_queue = InMemoryBatchQueue()
    scanner = BatchRecoveryScanner(store=store, queue=recovery_queue)

    import asyncio

    assert asyncio.run(scanner.reenqueue_missing()) == 1
    assert asyncio.run(recovery_queue.contains(job_id)) is True


def test_batch_job_read_is_scoped_to_authenticated_project() -> None:
    first_key = "an_first_valid"
    second_key = "an_second_valid"
    store = InMemoryBatchJobStore()
    service = BatchJobService(store=store, queue=InMemoryBatchQueue())
    auth_service = StaticApiKeyAuthService(
        {
            first_key: AuthContext(
                api_key_id="key_first",
                user_id="user_first",
                project_id="project_first",
                allowed_models=("test-model",),
            ),
            second_key: AuthContext(
                api_key_id="key_second",
                user_id="user_second",
                project_id="project_second",
                allowed_models=("test-model",),
            ),
        }
    )
    app = create_app(auth_service=auth_service, batch_service=service)

    with TestClient(app) as client:
        submit_response = client.post(
            "/v1/batch/jobs", json=_payload(), headers=auth_headers(first_key)
        )
        job_id = submit_response.json()["job_id"]
        forbidden_response = client.get(
            f"/v1/batch/jobs/{job_id}", headers=auth_headers(second_key)
        )
        owner_response = client.get(f"/v1/batch/jobs/{job_id}", headers=auth_headers(first_key))

    assert submit_response.status_code == 200
    assert forbidden_response.status_code == 404
    assert forbidden_response.json()["error"]["code"] == "batch_job_not_found"
    assert owner_response.status_code == 200
