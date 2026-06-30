"""ClickHouse integration."""

from typing import Protocol
from urllib.parse import urlparse


class ClickHouseLike(Protocol):
    def insert(
        self, table: str, rows: list[tuple[object, ...]], column_names: list[str]
    ) -> None: ...

    def command(self, sql: str) -> object: ...


class ClickHouseClient:
    """Thin wrapper around clickhouse-connect."""

    def __init__(self, client: ClickHouseLike) -> None:
        self._client = client

    @classmethod
    def from_settings(
        cls,
        *,
        url: str,
        database: str,
        username: str,
        password: str,
        secure: bool,
        verify: bool,
    ) -> "ClickHouseClient":
        import clickhouse_connect  # type: ignore[import-untyped]

        parsed = urlparse(url)
        return cls(
            clickhouse_connect.get_client(
                host=parsed.hostname or "localhost",
                port=parsed.port,
                username=username,
                password=password,
                database=database,
                secure=secure,
                verify=verify,
            )
        )

    def insert(self, table: str, rows: list[tuple[object, ...]], column_names: list[str]) -> None:
        self._client.insert(table, rows, column_names=column_names)

    def command(self, sql: str) -> object:
        return self._client.command(sql)
