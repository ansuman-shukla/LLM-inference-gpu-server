"""Tests for SQLAlchemy model registration."""

from backend.db.postgres import Base
from backend.models import load_models


def test_load_models_registers_foreign_key_targets() -> None:
    load_models()

    expected_tables = {
        "api_keys",
        "batch_jobs",
        "projects",
        "quota_policies",
        "request_audit_records",
        "users",
        "webhook_configs",
    }
    assert expected_tables.issubset(Base.metadata.tables)

    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            assert foreign_key.column.table.name in Base.metadata.tables
