"""phase 6 postgres schema

Revision ID: 20260529_0001
Revises: 
Create Date: 2026-05-29 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260529_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_projects_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
    )
    op.create_index(op.f("ix_projects_user_id"), "projects", ["user_id"], unique=False)

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=32), nullable=False),
        sa.Column("allowed_models", sa.JSON(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_api_keys_project_id_projects"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_api_keys_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
    )
    op.create_index(op.f("ix_api_keys_key_hash"), "api_keys", ["key_hash"], unique=True)
    op.create_index(op.f("ix_api_keys_key_prefix"), "api_keys", ["key_prefix"], unique=False)
    op.create_index(op.f("ix_api_keys_project_id"), "api_keys", ["project_id"], unique=False)
    op.create_index(op.f("ix_api_keys_user_id"), "api_keys", ["user_id"], unique=False)

    op.create_table(
        "quota_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("requests_per_minute", sa.Integer(), nullable=False),
        sa.Column("tokens_per_minute", sa.Integer(), nullable=False),
        sa.Column("concurrent_requests", sa.Integer(), nullable=False),
        sa.Column("daily_token_limit", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_quota_policies_project_id_projects"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quota_policies")),
    )
    op.create_index(op.f("ix_quota_policies_project_id"), "quota_policies", ["project_id"], unique=True)

    op.create_table(
        "batch_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("api_key_id", sa.String(length=36), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("input_uri", sa.String(length=2048), nullable=True),
        sa.Column("output_uri", sa.String(length=2048), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], name=op.f("fk_batch_jobs_api_key_id_api_keys"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_batch_jobs_project_id_projects"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_batch_jobs_user_id_users"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_batch_jobs")),
    )
    op.create_index(op.f("ix_batch_jobs_api_key_id"), "batch_jobs", ["api_key_id"], unique=False)
    op.create_index(op.f("ix_batch_jobs_model"), "batch_jobs", ["model"], unique=False)
    op.create_index(op.f("ix_batch_jobs_project_id"), "batch_jobs", ["project_id"], unique=False)
    op.create_index(op.f("ix_batch_jobs_status"), "batch_jobs", ["status"], unique=False)
    op.create_index(op.f("ix_batch_jobs_user_id"), "batch_jobs", ["user_id"], unique=False)

    op.create_table(
        "request_audit_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=80), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("api_key_id", sa.String(length=36), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("prompt_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], name=op.f("fk_request_audit_records_api_key_id_api_keys"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_request_audit_records_project_id_projects"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_request_audit_records_user_id_users"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_request_audit_records")),
    )
    op.create_index(op.f("ix_request_audit_records_api_key_id"), "request_audit_records", ["api_key_id"], unique=False)
    op.create_index(op.f("ix_request_audit_records_model"), "request_audit_records", ["model"], unique=False)
    op.create_index(op.f("ix_request_audit_records_project_id"), "request_audit_records", ["project_id"], unique=False)
    op.create_index(op.f("ix_request_audit_records_request_id"), "request_audit_records", ["request_id"], unique=True)
    op.create_index(op.f("ix_request_audit_records_status"), "request_audit_records", ["status"], unique=False)
    op.create_index(op.f("ix_request_audit_records_user_id"), "request_audit_records", ["user_id"], unique=False)

    op.create_table(
        "webhook_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_webhook_configs_project_id_projects"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_configs")),
    )
    op.create_index(op.f("ix_webhook_configs_project_id"), "webhook_configs", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_webhook_configs_project_id"), table_name="webhook_configs")
    op.drop_table("webhook_configs")
    op.drop_index(op.f("ix_request_audit_records_user_id"), table_name="request_audit_records")
    op.drop_index(op.f("ix_request_audit_records_status"), table_name="request_audit_records")
    op.drop_index(op.f("ix_request_audit_records_request_id"), table_name="request_audit_records")
    op.drop_index(op.f("ix_request_audit_records_project_id"), table_name="request_audit_records")
    op.drop_index(op.f("ix_request_audit_records_model"), table_name="request_audit_records")
    op.drop_index(op.f("ix_request_audit_records_api_key_id"), table_name="request_audit_records")
    op.drop_table("request_audit_records")
    op.drop_index(op.f("ix_batch_jobs_user_id"), table_name="batch_jobs")
    op.drop_index(op.f("ix_batch_jobs_status"), table_name="batch_jobs")
    op.drop_index(op.f("ix_batch_jobs_project_id"), table_name="batch_jobs")
    op.drop_index(op.f("ix_batch_jobs_model"), table_name="batch_jobs")
    op.drop_index(op.f("ix_batch_jobs_api_key_id"), table_name="batch_jobs")
    op.drop_table("batch_jobs")
    op.drop_index(op.f("ix_quota_policies_project_id"), table_name="quota_policies")
    op.drop_table("quota_policies")
    op.drop_index(op.f("ix_api_keys_user_id"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_project_id"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_key_prefix"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_key_hash"), table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_index(op.f("ix_projects_user_id"), table_name="projects")
    op.drop_table("projects")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
