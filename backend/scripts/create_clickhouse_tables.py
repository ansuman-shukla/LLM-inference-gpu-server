"""Create ClickHouse tables."""

from backend.core.config import get_settings
from backend.db.clickhouse import ClickHouseClient


def clickhouse_ddl(cluster: str) -> list[str]:
    return [
        "CREATE DATABASE IF NOT EXISTS inference_analytics",
        """
        CREATE TABLE IF NOT EXISTS inference_analytics.usage_events_local (
          event_time DateTime64(3),
          request_id String,
          user_id String,
          project_id String,
          api_key_id String,
          model String,
          status LowCardinality(String),
          prompt_tokens UInt32,
          completion_tokens UInt32,
          total_tokens UInt32,
          latency_ms Nullable(UInt32),
          error_code Nullable(String)
        ) ENGINE = MergeTree
        PARTITION BY toDate(event_time)
        ORDER BY (project_id, api_key_id, event_time)
        """,
        f"""
        CREATE TABLE IF NOT EXISTS inference_analytics.usage_events AS
        inference_analytics.usage_events_local
        ENGINE = Distributed('{cluster}', 'inference_analytics', 'usage_events_local', cityHash64(request_id))
        """,
        """
        CREATE TABLE IF NOT EXISTS inference_analytics.inference_events_local (
          event_time DateTime64(3),
          request_id String,
          event_type LowCardinality(String),
          user_id String,
          project_id String,
          api_key_id String,
          model String,
          status LowCardinality(String),
          latency_ms Nullable(UInt32),
          error_code Nullable(String)
        ) ENGINE = MergeTree
        PARTITION BY toDate(event_time)
        ORDER BY (project_id, api_key_id, event_time)
        """,
        f"""
        CREATE TABLE IF NOT EXISTS inference_analytics.inference_events AS
        inference_analytics.inference_events_local
        ENGINE = Distributed('{cluster}', 'inference_analytics', 'inference_events_local', cityHash64(request_id))
        """,
    ]


def main() -> None:
    settings = get_settings()
    client = ClickHouseClient.from_settings(
        url=settings.clickhouse_url,
        database=settings.clickhouse_database,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        secure=settings.clickhouse_secure,
        verify=settings.clickhouse_verify,
    )
    for statement in clickhouse_ddl(settings.clickhouse_cluster):
        client.command(statement)


if __name__ == "__main__":
    main()
