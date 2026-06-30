"""Tests for analytics events."""

from datetime import UTC, datetime

from backend.services.analytics.event_collector import AnalyticsCollector
from backend.services.analytics.event_models import USAGE_EVENT_COLUMNS, UsageEvent


def _usage_event(*, critical: bool = False) -> UsageEvent:
    return UsageEvent(
        event_time=datetime(2026, 5, 29, tzinfo=UTC),
        request_id="req_test",
        user_id="user_test",
        project_id="project_test",
        api_key_id="key_test",
        model="test-model",
        status="completed",
        prompt_tokens=3,
        completion_tokens=4,
        total_tokens=7,
        latency_ms=12,
        error_code=None,
        critical=critical,
    )


def test_event_serialization_matches_clickhouse_schema() -> None:
    event = _usage_event()

    row = event.to_row()

    assert event.table == "usage_events"
    assert len(row) == len(USAGE_EVENT_COLUMNS)
    assert row[USAGE_EVENT_COLUMNS.index("request_id")] == "req_test"
    assert row[USAGE_EVENT_COLUMNS.index("total_tokens")] == 7


def test_non_critical_event_drops_when_queue_full() -> None:
    collector = AnalyticsCollector(max_size=1)

    assert collector.collect(_usage_event()) is True
    assert collector.collect(_usage_event()) is False

    assert collector.dropped_non_critical == 1
    assert collector.queue.qsize() == 1


def test_clickhouse_failure_does_not_raise_into_request_path() -> None:
    class RaisingCollector:
        def collect(self, event: object) -> bool:
            raise RuntimeError("clickhouse down")

    from types import SimpleNamespace

    from backend.api.routes.chat_completions import _emit_usage_analytics
    from backend.services.auth.api_key_service import AuthContext
    from backend.services.inference.token_accounting import UsageRecord

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(analytics_collector=RaisingCollector()))
    )

    _emit_usage_analytics(
        request,
        auth_context=AuthContext(
            api_key_id="key_test",
            user_id="user_test",
            project_id="project_test",
            allowed_models=None,
        ),
        request_id="req_test",
        model="test-model",
        usage=UsageRecord(3, 4, 7, "completed"),
        latency_ms=12,
        error_code=None,
    )
