"""Request audit repository."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.request_audit import RequestAuditRecord
from backend.utils.time import utc_now


class RequestAuditRepository:
    """Database access for request audit records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, record: RequestAuditRecord) -> RequestAuditRecord:
        self._session.add(record)
        await self._session.flush()
        return record

    async def get(self, record_id: str) -> RequestAuditRecord | None:
        result = await self._session.execute(
            select(RequestAuditRecord).where(RequestAuditRecord.id == record_id)
        )
        return result.scalar_one_or_none()

    async def finalize(
        self,
        *,
        record_id: str,
        status: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        total_tokens: int | None,
        latency_ms: int | None,
        error_code: str | None,
    ) -> None:
        record = await self.get(record_id)
        if record is None:
            return
        record.status = status
        record.prompt_tokens = prompt_tokens
        record.completion_tokens = completion_tokens
        record.total_tokens = total_tokens
        record.latency_ms = latency_ms
        record.error_code = error_code
        record.completed_at = utc_now()
        await self._session.flush()
