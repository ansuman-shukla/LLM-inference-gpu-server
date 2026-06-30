"""Quota policy model."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.postgres import Base
from backend.utils.time import utc_now


class QuotaPolicy(Base):
    """Durable quota policy for a project."""

    __tablename__ = "quota_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), unique=True, index=True
    )
    requests_per_minute: Mapped[int] = mapped_column(Integer, default=60)
    tokens_per_minute: Mapped[int] = mapped_column(Integer, default=60_000)
    concurrent_requests: Mapped[int] = mapped_column(Integer, default=4)
    daily_token_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
