"""Integration tests for non-streaming chat completions."""

from typing import Any

from fastapi.testclient import TestClient

from backend.core.constants import REQUEST_ID_HEADER
from backend.main import create_app
from tests.conftest import (
    audit_service_for_tests,
    auth_headers,
    auth_service_for_tests,
    noop_admission_service,
)


class FakeVLLMClient:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None

    async def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payload = payload
        return {
            "id": "chatcmpl_fake",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "hello"},
                    "finish_reason": "stop",
                }
            ],
        }


def test_fake_vllm_response_returns_through_chat_completions_route() -> None:
    fake_client = FakeVLLMClient()

    with TestClient(
        create_app(
            vllm_client=fake_client,
            auth_service=auth_service_for_tests(),
            admission_service=noop_admission_service(),
            audit_service=audit_service_for_tests(),
        )
    ) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "hello"}],
            },
            headers={**auth_headers(), REQUEST_ID_HEADER: "req_test"},
        )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "req_test"
    assert response.json()["choices"][0]["message"]["content"] == "hello"
    assert fake_client.payload == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": False,
    }


def test_invalid_chat_completion_payload_returns_400_bad_request() -> None:
    with TestClient(
        create_app(
            vllm_client=FakeVLLMClient(),
            auth_service=auth_service_for_tests(),
            admission_service=noop_admission_service(),
            audit_service=audit_service_for_tests(),
        )
    ) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "messages": []},
            headers=auth_headers(),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"


def test_multimodal_chat_completion_payload_is_forwarded() -> None:
    fake_client = FakeVLLMClient()

    with TestClient(
        create_app(
            vllm_client=fake_client,
            auth_service=auth_service_for_tests(),
            admission_service=noop_admission_service(),
            audit_service=audit_service_for_tests(),
        )
    ) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "classify this image"},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/jpeg;base64,ZmFrZQ=="},
                            },
                        ],
                    }
                ],
                "response_format": {"type": "json_object"},
            },
            headers=auth_headers(),
        )

    assert response.status_code == 200
    assert fake_client.payload == {
        "model": "test-model",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "classify this image"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64,ZmFrZQ=="},
                    },
                ],
            }
        ],
        "stream": False,
        "response_format": {"type": "json_object"},
    }
