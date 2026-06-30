"""Integration tests for Sentry request capture."""

from typing import Any

from fastapi.testclient import TestClient

from backend.core.config import Settings
from backend.core.constants import REQUEST_ID_HEADER
from backend.core.errors import AppError
from backend.main import create_app
from backend.services.observability import sentry
from tests.conftest import (
    audit_service_for_tests,
    auth_headers,
    auth_service_for_tests,
    noop_admission_service,
)


class FakeScope:
    def __init__(self, sdk: "FakeSentrySdk") -> None:
        self._sdk = sdk
        self.tags: dict[str, str] = {}
        self.contexts: dict[str, object] = {}
        self.user: dict[str, object] | None = None

    def __enter__(self) -> "FakeScope":
        self._sdk.active_scope = self
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def set_tag(self, key: str, value: str) -> None:
        self.tags[key] = value

    def set_context(self, key: str, value: object) -> None:
        self.contexts[key] = value

    def set_user(self, user: dict[str, object]) -> None:
        self.user = user


class FakeSentrySdk:
    def __init__(self, *, fail_capture: bool = False) -> None:
        self.initialized = False
        self.fail_capture = fail_capture
        self.active_scope: FakeScope | None = None
        self.captured: list[dict[str, object]] = []

    def init(self, **kwargs: object) -> None:
        self.initialized = True
        self.options = kwargs

    def push_scope(self) -> FakeScope:
        return FakeScope(self)

    def configure_scope(self) -> FakeScope:
        return FakeScope(self)

    def capture_exception(self, exc: BaseException) -> str:
        if self.fail_capture:
            raise RuntimeError("sentry unavailable")
        self.captured.append({"exception": exc, "scope": self.active_scope})
        return f"event-{len(self.captured)}"


class FailingVLLMClient:
    async def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise AppError(
            message="vLLM upstream timed out",
            code="upstream_timeout",
            status_code=504,
            type="server_error",
        )


def _app() -> Any:
    return create_app(
        settings=Settings(sentry_dsn="http://public@sentry.local/1", app_env="test"),
        vllm_client=FailingVLLMClient(),
        auth_service=auth_service_for_tests(),
        admission_service=noop_admission_service(),
        audit_service=audit_service_for_tests(),
    )


def _post_chat(client: TestClient) -> Any:
    return client.post(
        "/v1/chat/completions",
        json={"model": "test-model", "messages": [{"role": "user", "content": "hello"}]},
        headers={**auth_headers(), REQUEST_ID_HEADER: "req_sentry"},
    )


def test_forced_exception_is_captured_with_request_tags(monkeypatch) -> None:
    fake_sdk = FakeSentrySdk()
    monkeypatch.setattr(sentry, "_sentry_sdk", fake_sdk)

    with TestClient(_app()) as client:
        response = _post_chat(client)

    assert response.status_code == 504
    assert fake_sdk.initialized is True
    assert len(fake_sdk.captured) == 1
    scope = fake_sdk.captured[0]["scope"]
    assert isinstance(scope, FakeScope)
    assert scope.tags["request_id"] == "req_sentry"
    assert scope.tags["endpoint"] == "/v1/chat/completions"
    assert scope.tags["model"] == "test-model"
    assert scope.tags["stream"] == "False"
    assert scope.tags["error_code"] == "upstream_timeout"
    assert scope.tags["user_id"] == "user_test"
    assert scope.tags["project_id"] == "project_test"
    assert scope.tags["api_key_id"] == "key_test"


def test_sentry_unavailable_does_not_break_request(monkeypatch) -> None:
    fake_sdk = FakeSentrySdk(fail_capture=True)
    monkeypatch.setattr(sentry, "_sentry_sdk", fake_sdk)

    with TestClient(_app()) as client:
        response = _post_chat(client)

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "upstream_timeout"
