"""API key service."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from secrets import token_urlsafe

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.errors import AppError
from backend.models.api_key import ApiKey
from backend.repositories.api_key_repository import ApiKeyRepository
from backend.services.auth.password_hashing import hash_api_key, key_debug_prefix
from backend.utils.time import utc_now


@dataclass(frozen=True)
class AuthContext:
    """Authenticated API key context attached to request state."""

    api_key_id: str
    user_id: str
    project_id: str
    allowed_models: tuple[str, ...] | None


@dataclass(frozen=True)
class CreatedApiKey:
    """Created API key record plus the raw key shown once."""

    raw_key: str
    api_key_id: str
    key_prefix: str


class ApiKeyService:
    """Authenticate and create API keys."""

    def __init__(
        self,
        repository_factory: type[ApiKeyRepository],
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        key_prefix: str,
    ) -> None:
        self._repository_factory = repository_factory
        self._sessionmaker = sessionmaker
        self._key_prefix = key_prefix

    async def authenticate(self, raw_key: str) -> AuthContext:
        """Validate a raw API key and return request auth context."""
        key_hash = hash_api_key(raw_key)
        async with self._sessionmaker.begin() as session:
            repository = self._repository_factory(session)
            api_key = await repository.get_by_hash(key_hash)
            if api_key is None:
                raise invalid_api_key_error()
            validate_api_key_state(api_key)
            context = auth_context_from_api_key(api_key)
            await repository.mark_used(api_key)
            return context

    async def create_api_key(
        self,
        *,
        user_id: str,
        project_id: str,
        name: str,
        allowed_models: Sequence[str] | None,
        expires_at: datetime | None = None,
    ) -> CreatedApiKey:
        """Create an API key and return the raw key once."""
        raw_key = generate_api_key(self._key_prefix)
        async with self._sessionmaker.begin() as session:
            repository = self._repository_factory(session)
            api_key = await repository.create(
                user_id=user_id,
                project_id=project_id,
                name=name,
                key_hash=hash_api_key(raw_key),
                key_prefix=key_debug_prefix(raw_key),
                allowed_models=allowed_models,
                expires_at=expires_at,
            )
            return CreatedApiKey(
                raw_key=raw_key, api_key_id=api_key.id, key_prefix=api_key.key_prefix
            )


class StaticApiKeyAuthService:
    """Test helper service for in-process auth integration tests."""

    def __init__(
        self, contexts: dict[str, AuthContext], revoked_keys: set[str] | None = None
    ) -> None:
        self._contexts = contexts
        self._revoked_keys = revoked_keys or set()

    async def authenticate(self, raw_key: str) -> AuthContext:
        if raw_key in self._revoked_keys:
            raise revoked_api_key_error()
        context = self._contexts.get(raw_key)
        if context is None:
            raise invalid_api_key_error()
        return context


def generate_api_key(prefix: str = "an") -> str:
    """Generate a raw API key in the public `an_...` format."""
    normalized_prefix = prefix[:-1] if prefix.endswith("_") else prefix
    return f"{normalized_prefix}_{token_urlsafe(32)}"


def auth_context_from_api_key(api_key: ApiKey) -> AuthContext:
    """Build auth context from a persisted API key row."""
    allowed_models = (
        tuple(str(model) for model in api_key.allowed_models)
        if api_key.allowed_models is not None
        else None
    )
    return AuthContext(
        api_key_id=api_key.id,
        user_id=api_key.user_id,
        project_id=api_key.project_id,
        allowed_models=allowed_models,
    )


def validate_api_key_state(api_key: ApiKey) -> None:
    """Reject revoked or expired API keys."""
    if api_key.revoked_at is not None:
        raise revoked_api_key_error()
    if api_key.expires_at is not None and api_key.expires_at <= utc_now():
        raise expired_api_key_error()


def ensure_model_allowed(auth_context: AuthContext, model: str) -> None:
    """Raise when an API key is not allowed to use the requested model."""
    if auth_context.allowed_models is None:
        return
    if model not in auth_context.allowed_models:
        raise AppError(
            message="API key is not allowed to access the requested model",
            code="model_not_allowed",
            status_code=403,
            type="invalid_request_error",
            param="model",
        )


def missing_api_key_error() -> AppError:
    return AppError(
        message="Missing API key",
        code="missing_api_key",
        status_code=401,
        type="invalid_request_error",
    )


def invalid_api_key_error() -> AppError:
    return AppError(
        message="Invalid API key",
        code="invalid_api_key",
        status_code=401,
        type="invalid_request_error",
    )


def expired_api_key_error() -> AppError:
    return AppError(
        message="API key has expired",
        code="expired_api_key",
        status_code=401,
        type="invalid_request_error",
    )


def revoked_api_key_error() -> AppError:
    return AppError(
        message="API key has been revoked",
        code="revoked_api_key",
        status_code=401,
        type="invalid_request_error",
    )
