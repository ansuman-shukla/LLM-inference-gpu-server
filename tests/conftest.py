"""Pytest configuration."""

import pytest

from backend.core.config import get_settings
from backend.services.auth.api_key_service import AuthContext, StaticApiKeyAuthService
from backend.services.inference.usage_finalizer import InMemoryRequestAuditService
from backend.services.observability import sentry
from backend.services.rate_limit.admission import NoopAdmissionService


@pytest.fixture(autouse=True)
def disable_sentry_dsn_for_tests(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "")
    monkeypatch.setattr(sentry, "_sentry_enabled", False)
    get_settings.cache_clear()
    yield
    monkeypatch.setattr(sentry, "_sentry_enabled", False)
    get_settings.cache_clear()


TEST_API_KEY = "an_test_valid"


def auth_service_for_tests(
    *, allowed_models: tuple[str, ...] | None = ("test-model",), revoked: bool = False
) -> StaticApiKeyAuthService:
    return StaticApiKeyAuthService(
        {
            TEST_API_KEY: AuthContext(
                api_key_id="key_test",
                user_id="user_test",
                project_id="project_test",
                allowed_models=allowed_models,
            )
        },
        revoked_keys={TEST_API_KEY} if revoked else None,
    )


def auth_headers(raw_key: str = TEST_API_KEY) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}"}


class FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.values: dict[str, int | str] = {}
        self.expirations: dict[str, int] = {}
        self.lists: dict[str, list[str]] = {}
        self.fail = fail

    def _maybe_fail(self) -> None:
        if self.fail:
            raise RuntimeError("redis unavailable")

    async def ping(self) -> bool:
        self._maybe_fail()
        return True

    async def get(self, name: str) -> object | None:
        self._maybe_fail()
        return self.values.get(name)

    async def set(self, name: str, value: object, ex: int | None = None) -> object:
        self._maybe_fail()
        self.values[name] = value if isinstance(value, str) else str(value)
        if ex is not None:
            self.expirations[name] = ex
        return True

    async def incr(self, name: str) -> int:
        self._maybe_fail()
        value = int(self.values.get(name, 0)) + 1
        self.values[name] = value
        return value

    async def decr(self, name: str) -> int:
        self._maybe_fail()
        value = int(self.values.get(name, 0)) - 1
        self.values[name] = value
        return value

    async def incrby(self, name: str, amount: int) -> int:
        self._maybe_fail()
        value = int(self.values.get(name, 0)) + amount
        self.values[name] = value
        return value

    async def decrby(self, name: str, amount: int) -> int:
        self._maybe_fail()
        value = int(self.values.get(name, 0)) - amount
        self.values[name] = value
        return value

    async def expire(self, name: str, time: int) -> object:
        self._maybe_fail()
        self.expirations[name] = time
        return True

    async def delete(self, *names: str) -> int:
        self._maybe_fail()
        deleted = 0
        for name in names:
            if name in self.values:
                deleted += 1
                del self.values[name]
            if name in self.lists:
                deleted += 1
                del self.lists[name]
        return deleted

    async def rpush(self, name: str, value: str) -> int:
        self._maybe_fail()
        values = self.lists.setdefault(name, [])
        values.append(value)
        return len(values)

    async def lpop(self, name: str) -> object | None:
        self._maybe_fail()
        values = self.lists.get(name, [])
        if not values:
            return None
        return values.pop(0)

    async def lrange(self, name: str, start: int, end: int) -> list[object]:
        self._maybe_fail()
        values = self.lists.get(name, [])
        stop = None if end == -1 else end + 1
        return list(values[start:stop])

    async def aclose(self) -> None:
        return None


def noop_admission_service() -> NoopAdmissionService:
    return NoopAdmissionService()


def audit_service_for_tests() -> InMemoryRequestAuditService:
    return InMemoryRequestAuditService()
