"""Tests for batch job services."""

import asyncio
from typing import Any

from backend.core.config import Settings
from backend.schemas.batch_job import BatchJobCreateRequest
from backend.services.auth.api_key_service import AuthContext
from backend.services.batch.batch_queue import InMemoryBatchQueue
from backend.services.batch.batch_service import (
    CANCELLED,
    QUEUED,
    RUNNING,
    SUCCEEDED,
    BatchJobService,
    InMemoryBatchJobStore,
    can_transition,
)
from backend.services.batch.batch_worker import BatchWorker
from backend.services.batch.recovery_scanner import BatchRecoveryScanner
from backend.services.inference.token_accounting import HeuristicTokenEstimator
from tests.conftest import audit_service_for_tests, noop_admission_service


class FakeVLLMClient:
    def __init__(self) -> None:
        self.calls = 0

    async def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return {
            "id": "chatcmpl_batch",
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


def _auth_context() -> AuthContext:
    return AuthContext(
        api_key_id="key_test",
        user_id="user_test",
        project_id="project_test",
        allowed_models=None,
    )


def _request() -> BatchJobCreateRequest:
    return BatchJobCreateRequest(
        model="test-model",
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=8,
    )


def test_batch_status_transitions_are_valid() -> None:
    assert can_transition(QUEUED, RUNNING) is True
    assert can_transition(QUEUED, CANCELLED) is True
    assert can_transition(RUNNING, SUCCEEDED) is True
    assert can_transition(SUCCEEDED, RUNNING) is False
    assert can_transition(CANCELLED, RUNNING) is False


def test_worker_does_not_run_cancelled_job() -> None:
    async def run() -> None:
        store = InMemoryBatchJobStore()
        queue = InMemoryBatchQueue()
        service = BatchJobService(store=store, queue=queue)
        job = await service.submit(auth_context=_auth_context(), request_body=_request())
        await service.cancel(job.id)
        vllm_client = FakeVLLMClient()

        worker = BatchWorker(
            store=store,
            queue=queue,
            vllm_client=vllm_client,
            admission_service=noop_admission_service(),
            token_estimator=HeuristicTokenEstimator(),
            audit_service=audit_service_for_tests(),
            settings=Settings(),
        )

        assert await worker.process_one() is False
        assert vllm_client.calls == 0
        assert (await store.get(job.id)).status == CANCELLED  # type: ignore[union-attr]

    asyncio.run(run())


def test_recovery_scanner_reenqueues_stuck_queued_job() -> None:
    async def run() -> None:
        store = InMemoryBatchJobStore()
        failing_queue = InMemoryBatchQueue(fail_enqueue=True)
        service = BatchJobService(store=store, queue=failing_queue)
        job = await service.submit(auth_context=_auth_context(), request_body=_request())

        recovery_queue = InMemoryBatchQueue()
        scanner = BatchRecoveryScanner(store=store, queue=recovery_queue)

        assert await recovery_queue.contains(job.id) is False
        assert await scanner.reenqueue_missing() == 1
        assert await recovery_queue.contains(job.id) is True

    asyncio.run(run())
