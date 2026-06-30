"""Tests for Sentry integration."""

from backend.core.errors import AppError
from backend.services.observability import sentry


class FakeScope:
    def __init__(self) -> None:
        self.tags: dict[str, str] = {}
        self.contexts: dict[str, object] = {}
        self.user: dict[str, object] | None = None

    def __enter__(self) -> "FakeScope":
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
    def __init__(self) -> None:
        self.captured: list[BaseException] = []

    def push_scope(self) -> FakeScope:
        return FakeScope()

    def configure_scope(self) -> FakeScope:
        return FakeScope()

    def capture_exception(self, exc: BaseException) -> str:
        self.captured.append(exc)
        return "event-1"


def test_sentry_scrubber_removes_secrets() -> None:
    event = {
        "request": {
            "headers": {"authorization": "Bearer an_supersecretapikeyvalue"},
            "data": {"messages": [{"role": "user", "content": "secret prompt"}]},
        },
        "extra": {
            "api_key": "an_anothersecretapikey",
            "api_key_id": "key_safe_identifier",
            "database_url": "postgresql://gpu:secret@db.internal:5432/app",
            "cloudflared_tunnel_token": "token-value",
        },
    }

    scrubbed = sentry.scrub_sentry_event(event)

    assert scrubbed is not None
    assert scrubbed["request"]["headers"]["authorization"] == sentry.REDACTED
    assert scrubbed["request"]["data"]["messages"] == sentry.REDACTED
    assert scrubbed["extra"]["api_key"] == sentry.REDACTED
    assert scrubbed["extra"]["api_key_id"] == "key_safe_identifier"
    assert scrubbed["extra"]["database_url"] == "postgresql://gpu:***@db.internal:5432/app"
    assert scrubbed["extra"]["cloudflared_tunnel_token"] == sentry.REDACTED


def test_expected_client_errors_are_not_captured(monkeypatch) -> None:
    fake_sdk = FakeSentrySdk()
    monkeypatch.setattr(sentry, "_sentry_sdk", fake_sdk)

    for status_code in (400, 401, 429):
        event_id = sentry.capture_exception(
            AppError(
                message="client error",
                code="expected_client_error",
                status_code=status_code,
                type="invalid_request_error",
            )
        )
        assert event_id is None

    assert fake_sdk.captured == []
