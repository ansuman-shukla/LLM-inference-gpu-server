"""Analytics event models."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

AnalyticsTable = Literal["usage_events", "inference_events"]

USAGE_EVENT_COLUMNS = [
    "event_time",
    "request_id",
    "user_id",
    "project_id",
    "api_key_id",
    "model",
    "status",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "latency_ms",
    "error_code",
]

INFERENCE_EVENT_COLUMNS = [
    "event_time",
    "request_id",
    "event_type",
    "user_id",
    "project_id",
    "api_key_id",
    "model",
    "status",
    "latency_ms",
    "error_code",
]


@dataclass(frozen=True)
class UsageEvent:
    event_time: datetime
    request_id: str
    user_id: str
    project_id: str
    api_key_id: str
    model: str
    status: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int | None
    error_code: str | None
    critical: bool = False

    @property
    def table(self) -> AnalyticsTable:
        return "usage_events"

    def to_row(self) -> tuple[object, ...]:
        return (
            self.event_time,
            self.request_id,
            self.user_id,
            self.project_id,
            self.api_key_id,
            self.model,
            self.status,
            self.prompt_tokens,
            self.completion_tokens,
            self.total_tokens,
            self.latency_ms,
            self.error_code,
        )


@dataclass(frozen=True)
class InferenceEvent:
    event_time: datetime
    request_id: str
    event_type: str
    user_id: str
    project_id: str
    api_key_id: str
    model: str
    status: str
    latency_ms: int | None
    error_code: str | None
    critical: bool = False

    @property
    def table(self) -> AnalyticsTable:
        return "inference_events"

    def to_row(self) -> tuple[object, ...]:
        return (
            self.event_time,
            self.request_id,
            self.event_type,
            self.user_id,
            self.project_id,
            self.api_key_id,
            self.model,
            self.status,
            self.latency_ms,
            self.error_code,
        )


AnalyticsEvent = UsageEvent | InferenceEvent


def columns_for_table(table: AnalyticsTable) -> list[str]:
    if table == "usage_events":
        return USAGE_EVENT_COLUMNS
    return INFERENCE_EVENT_COLUMNS
