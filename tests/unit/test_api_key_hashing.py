"""Tests for API key hashing."""

from types import SimpleNamespace

import pytest

from backend.core.errors import AppError
from backend.services.auth.api_key_service import (
    AuthContext,
    ApiKeyService,
    StaticApiKeyAuthService,
    ensure_model_allowed,
    generate_api_key,
)
from backend.services.auth.password_hashing import hash_api_key, key_debug_prefix
from backend.utils.time import utc_now


def test_raw_api_key_hashing_is_stable_and_not_plaintext() -> None:
    raw_key = "an_test_secret"

    hashed = hash_api_key(raw_key)

    assert hashed == hash_api_key(raw_key)
    assert hashed != raw_key
    assert len(hashed) == 64


def test_key_generation_uses_yral_prefix() -> None:
    raw_key = generate_api_key("an")

    assert raw_key.startswith("an_")
    assert key_debug_prefix(raw_key) == raw_key[:16]


def test_invalid_key_returns_401_error() -> None:
    service = StaticApiKeyAuthService({})

    async def scenario() -> None:
        await service.authenticate("an_missing")

    import asyncio

    with pytest.raises(AppError) as exc_info:
        asyncio.run(scenario())

    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "invalid_api_key"


def test_created_api_key_is_committed_before_script_prints_raw_key() -> None:
    sessionmaker = _FakeSessionmaker()
    service = ApiKeyService(_PersistingApiKeyRepository, sessionmaker, key_prefix="an")

    async def scenario() -> AuthContext:
        created = await service.create_api_key(
            user_id="user_test",
            project_id="project_test",
            name="test-key",
            allowed_models=("test-model",),
        )
        return await service.authenticate(created.raw_key)

    import asyncio

    auth_context = asyncio.run(scenario())

    assert auth_context.user_id == "user_test"
    assert auth_context.project_id == "project_test"
    assert auth_context.allowed_models == ("test-model",)


def test_disallowed_model_returns_403_error() -> None:
    auth_context = AuthContext(
        api_key_id="key_test",
        user_id="user_test",
        project_id="project_test",
        allowed_models=("allowed-model",),
    )

    with pytest.raises(AppError) as exc_info:
        ensure_model_allowed(auth_context, "blocked-model")

    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "model_not_allowed"


class _FakeSessionmaker:
    def __init__(self) -> None:
        self.committed_keys: dict[str, SimpleNamespace] = {}

    def begin(self) -> "_FakeTransaction":
        return _FakeTransaction(self)


class _FakeTransaction:
    def __init__(self, sessionmaker: _FakeSessionmaker) -> None:
        self.session = _FakeSession(sessionmaker.committed_keys)

    async def __aenter__(self) -> "_FakeSession":
        return self.session

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is None:
            self.session.commit()


class _FakeSession:
    def __init__(self, committed_keys: dict[str, SimpleNamespace]) -> None:
        self.committed_keys = committed_keys
        self.pending_keys: dict[str, SimpleNamespace] = {}

    def commit(self) -> None:
        self.committed_keys.update(self.pending_keys)


class _PersistingApiKeyRepository:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def get_by_hash(self, key_hash: str) -> SimpleNamespace | None:
        return self._session.committed_keys.get(key_hash)

    async def create(
        self,
        *,
        user_id: str,
        project_id: str,
        name: str,
        key_hash: str,
        key_prefix: str,
        allowed_models: tuple[str, ...] | None,
        expires_at: object | None = None,
    ) -> SimpleNamespace:
        api_key = SimpleNamespace(
            id="key_persisted",
            user_id=user_id,
            project_id=project_id,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            allowed_models=list(allowed_models) if allowed_models is not None else None,
            expires_at=expires_at,
            revoked_at=None,
            created_at=utc_now(),
            last_used_at=None,
        )
        self._session.pending_keys[key_hash] = api_key
        return api_key

    async def mark_used(self, api_key: SimpleNamespace) -> None:
        api_key.last_used_at = utc_now()
