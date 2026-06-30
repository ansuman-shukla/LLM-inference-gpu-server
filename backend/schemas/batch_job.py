"""Batch job schemas."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from backend.schemas.chat_completion import ChatMessage


BatchJobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class BatchJobCreateRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop: str | list[str] | None = None
    metadata: dict[str, Any] | None = None

    model_config = ConfigDict(extra="allow")


class BatchJobSubmitResponse(BaseModel):
    job_id: str
    status: BatchJobStatus


class BatchJobResponse(BaseModel):
    job_id: str
    status: BatchJobStatus
    model: str
    request_count: int
    completed_count: int
    failed_count: int
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
