"""API key repository."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.api_key import ApiKey
from backend.utils.time import utc_now


class ApiKeyRepository:
    """Database access for API key records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_hash(self, key_hash: str) -> ApiKey | None:
        """Return an API key by its hashed raw key."""
        result = await self._session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: str,
        project_id: str,
        name: str,
        key_hash: str,
        key_prefix: str,
        allowed_models: Sequence[str] | None,
        expires_at: datetime | None = None,
    ) -> ApiKey:
        """Create and persist an API key record."""
        api_key = ApiKey(
            user_id=user_id,
            project_id=project_id,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            allowed_models=list(allowed_models) if allowed_models is not None else None,
            expires_at=expires_at,
        )
        self._session.add(api_key)
        await self._session.flush()
        return api_key

    async def mark_used(self, api_key: ApiKey) -> None:
        """Record successful API key use."""
        api_key.last_used_at = utc_now()
        await self._session.flush()
