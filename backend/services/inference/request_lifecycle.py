"""Inference request lifecycle management."""

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
import json

from backend.models.request_audit import RequestAuditRecord
from backend.schemas.chat_completion import ChatMessage
from backend.services.auth.api_key_service import AuthContext
from backend.services.inference.token_accounting import UsageRecord


@dataclass(frozen=True)
class AuditStart:
    request_id: str
    user_id: str
    project_id: str
    api_key_id: str
    model: str
    prompt_hash: str | None


@dataclass(frozen=True)
class AuditFinal:
    record_id: str
    status: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    latency_ms: int | None
    error_code: str | None


def build_audit_start(
    *,
    request_id: str,
    auth_context: AuthContext,
    model: str,
    messages: Sequence[ChatMessage],
) -> AuditStart:
    """Build audit start data without raw prompt or raw API key material."""
    return AuditStart(
        request_id=request_id,
        user_id=auth_context.user_id,
        project_id=auth_context.project_id,
        api_key_id=auth_context.api_key_id,
        model=model,
        prompt_hash=hash_prompt(messages),
    )


def audit_record_from_start(start: AuditStart) -> RequestAuditRecord:
    return RequestAuditRecord(
        request_id=start.request_id,
        user_id=start.user_id,
        project_id=start.project_id,
        api_key_id=start.api_key_id,
        model=start.model,
        status="accepted",
        prompt_hash=start.prompt_hash,
    )


def build_audit_final(
    *,
    record_id: str,
    usage: UsageRecord,
    latency_ms: int | None,
    error_code: str | None = None,
) -> AuditFinal:
    return AuditFinal(
        record_id=record_id,
        status=usage.status,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        latency_ms=latency_ms,
        error_code=error_code,
    )


def hash_prompt(messages: Sequence[ChatMessage]) -> str | None:
    if not messages:
        return None
    digest = sha256()
    for message in messages:
        digest.update(message.role.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_serialize_message_content(message).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _serialize_message_content(message: ChatMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    payload = [part.model_dump(mode="json", exclude_none=True) for part in message.content]
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
