"""Usage finalization helpers."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.repositories.request_audit_repository import RequestAuditRepository
from backend.services.inference.request_lifecycle import (
    AuditFinal,
    AuditStart,
    audit_record_from_start,
)


class RequestAuditService:
    """Postgres-backed request audit lifecycle service."""

    def __init__(
        self,
        repository_factory: type[RequestAuditRepository],
        sessionmaker: async_sessionmaker[AsyncSession],
    ) -> None:
        self._repository_factory = repository_factory
        self._sessionmaker = sessionmaker

    async def start(self, audit: AuditStart) -> str:
        async with self._sessionmaker.begin() as session:
            repository = self._repository_factory(session)
            record = await repository.create(audit_record_from_start(audit))
            return record.id

    async def finalize(self, final: AuditFinal) -> None:
        async with self._sessionmaker.begin() as session:
            repository = self._repository_factory(session)
            await repository.finalize(
                record_id=final.record_id,
                status=final.status,
                prompt_tokens=final.prompt_tokens,
                completion_tokens=final.completion_tokens,
                total_tokens=final.total_tokens,
                latency_ms=final.latency_ms,
                error_code=final.error_code,
            )


@dataclass
class InMemoryAuditRecord:
    record_id: str
    start: AuditStart
    final: AuditFinal | None = None


class InMemoryRequestAuditService:
    """Test audit lifecycle service."""

    def __init__(self) -> None:
        self.records: list[InMemoryAuditRecord] = []

    async def start(self, audit: AuditStart) -> str:
        record_id = f"audit_{len(self.records) + 1}"
        self.records.append(InMemoryAuditRecord(record_id=record_id, start=audit))
        return record_id

    async def finalize(self, final: AuditFinal) -> None:
        for record in self.records:
            if record.record_id == final.record_id:
                record.final = final
                return
