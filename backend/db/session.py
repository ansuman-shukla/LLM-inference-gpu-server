"""Database session helpers."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.postgres import session_scope


async def iter_session(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield one managed async SQLAlchemy session."""
    async for session in session_scope(sessionmaker):
        yield session
