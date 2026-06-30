"""Integration tests for authentication flow."""

from typing import Any

from fastapi.testclient import TestClient

from backend.main import create_app
from backend.services.auth.api_key_service import (
    AuthContext,
    StaticApiKeyAuthService,
    generate_api_key,
)
from tests.conftest import audit_service_for_tests, noop_admission_service


class FakeVLLMClient:
    async def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": "chatcmpl_auth",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "authorized"},
                    "finish_reason": "stop",
                }
            ],
        }


def _auth_service(raw_key: str, *, revoked: bool = False) -> StaticApiKeyAuthService:
    return StaticApiKeyAuthService(
        {
            raw_key: AuthContext(
                api_key_id="key_generated",
                user_id="user_test",
                project_id="project_test",
                allowed_models=("test-model",),
            )
        },
        revoked_keys={raw_key} if revoked else None,
    )


def test_generated_key_can_call_chat_completions() -> None:
    raw_key = generate_api_key()
    app = create_app(
        vllm_client=FakeVLLMClient(),
        auth_service=_auth_service(raw_key),
        admission_service=noop_admission_service(),
        audit_service=audit_service_for_tests(),
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "messages": [{"role": "user", "content": "hello"}]},
            headers={"Authorization": f"Bearer {raw_key}"},
        )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "authorized"


def test_missing_key_cannot_call_chat_completions() -> None:
    raw_key = generate_api_key()
    app = create_app(
        vllm_client=FakeVLLMClient(),
        auth_service=_auth_service(raw_key),
        admission_service=noop_admission_service(),
        audit_service=audit_service_for_tests(),
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "messages": [{"role": "user", "content": "hello"}]},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_api_key"


def test_revoked_key_cannot_call_chat_completions() -> None:
    raw_key = generate_api_key()
    app = create_app(
        vllm_client=FakeVLLMClient(),
        auth_service=_auth_service(raw_key, revoked=True),
        admission_service=noop_admission_service(),
        audit_service=audit_service_for_tests(),
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "messages": [{"role": "user", "content": "hello"}]},
            headers={"Authorization": f"Bearer {raw_key}"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "revoked_api_key"
