"""Baseline existing Rebly AI schema.

Revision ID: 0001_existing_schema_baseline
Revises:
Create Date: 2026-07-10

This migration is intentionally defensive: on an existing database it leaves
current tables and data in place; on a new database it creates the legacy
schema that previously came only from Base.metadata.create_all().
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_existing_schema_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _create_index(name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    bind = op.get_bind()
    existing = {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}
    if name not in existing:
        op.create_index(name, table_name, columns, unique=unique)


def upgrade() -> None:
    if not _has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("hashed_password", sa.String(length=255), nullable=True),
            sa.Column("google_sub", sa.String(length=255), nullable=True),
            sa.Column("first_name", sa.String(length=120), nullable=True),
            sa.Column("last_name", sa.String(length=120), nullable=True),
            sa.Column("avatar_url", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("email"),
            sa.UniqueConstraint("google_sub"),
        )
    _create_index("ix_users_id", "users", ["id"])
    _create_index("ix_users_email", "users", ["email"], unique=True)
    _create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)

    if not _has_table("telegram_bot_integrations"):
        op.create_table(
            "telegram_bot_integrations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("encrypted_bot_token", sa.Text(), nullable=False),
            sa.Column("target_chat_id", sa.String(length=255), nullable=False),
            sa.Column("bot_username", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id"),
        )
    _create_index("ix_telegram_bot_integrations_id", "telegram_bot_integrations", ["id"])
    _create_index("ix_telegram_bot_integrations_user_id", "telegram_bot_integrations", ["user_id"], unique=True)

    if not _has_table("instagram_integrations"):
        op.create_table(
            "instagram_integrations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("encrypted_access_token", sa.Text(), nullable=False),
            sa.Column("ig_user_id", sa.String(length=255), nullable=False),
            sa.Column("username", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id"),
        )
    _create_index("ix_instagram_integrations_id", "instagram_integrations", ["id"])
    _create_index("ix_instagram_integrations_user_id", "instagram_integrations", ["user_id"], unique=True)

    if not _has_table("integration_providers"):
        op.create_table(
            "integration_providers",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("key", sa.String(length=80), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("auth_type", sa.String(length=40), nullable=False),
            sa.Column("logo", sa.String(length=255), nullable=True),
            sa.Column("docs_url", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("key"),
        )
    _create_index("ix_integration_providers_id", "integration_providers", ["id"])
    _create_index("ix_integration_providers_key", "integration_providers", ["key"], unique=True)

    if not _has_table("user_integrations"):
        op.create_table(
            "user_integrations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("provider_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["provider_id"], ["integration_providers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index("ix_user_integrations_id", "user_integrations", ["id"])
    _create_index("ix_user_integrations_user_id", "user_integrations", ["user_id"])
    _create_index("ix_user_integrations_provider_id", "user_integrations", ["provider_id"])

    if not _has_table("integration_accounts"):
        op.create_table(
            "integration_accounts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_integration_id", sa.Integer(), nullable=False),
            sa.Column("provider_id", sa.Integer(), nullable=False),
            sa.Column("account_identifier", sa.String(length=255), nullable=False),
            sa.Column("account_label", sa.String(length=255), nullable=True),
            sa.Column("account_type", sa.String(length=80), nullable=True),
            sa.Column("is_default", sa.Boolean(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["provider_id"], ["integration_providers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_integration_id"], ["user_integrations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index("ix_integration_accounts_id", "integration_accounts", ["id"])
    _create_index("ix_integration_accounts_user_integration_id", "integration_accounts", ["user_integration_id"])
    _create_index("ix_integration_accounts_provider_id", "integration_accounts", ["provider_id"])
    _create_index("ix_integration_accounts_account_identifier", "integration_accounts", ["account_identifier"])

    if not _has_table("integration_tokens"):
        op.create_table(
            "integration_tokens",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_integration_id", sa.Integer(), nullable=False),
            sa.Column("integration_account_id", sa.Integer(), nullable=False),
            sa.Column("encrypted_access_token", sa.Text(), nullable=True),
            sa.Column("encrypted_refresh_token", sa.Text(), nullable=True),
            sa.Column("token_type", sa.String(length=80), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("scopes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["integration_account_id"], ["integration_accounts.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_integration_id"], ["user_integrations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index("ix_integration_tokens_id", "integration_tokens", ["id"])
    _create_index("ix_integration_tokens_user_integration_id", "integration_tokens", ["user_integration_id"])
    _create_index("ix_integration_tokens_integration_account_id", "integration_tokens", ["integration_account_id"])

    if not _has_table("integration_capabilities"):
        op.create_table(
            "integration_capabilities",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("provider_id", sa.Integer(), nullable=False),
            sa.Column("key", sa.String(length=120), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("scope", sa.Text(), nullable=True),
            sa.Column("access_level", sa.String(length=40), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["provider_id"], ["integration_providers.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index("ix_integration_capabilities_id", "integration_capabilities", ["id"])
    _create_index("ix_integration_capabilities_provider_id", "integration_capabilities", ["provider_id"])
    _create_index("ix_integration_capabilities_key", "integration_capabilities", ["key"])

    if not _has_table("scheduled_posts"):
        op.create_table(
            "scheduled_posts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("platform", sa.String(length=40), nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("media_url", sa.Text(), nullable=True),
            sa.Column("media_type", sa.String(length=120), nullable=True),
            sa.Column("publish_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("timezone", sa.String(length=80), nullable=False),
            sa.Column("repeat_rule", sa.String(length=160), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("source", sa.String(length=80), nullable=True),
            sa.Column("run_id", sa.String(length=80), nullable=True),
            sa.Column("external_id", sa.String(length=255), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["account_id"], ["integration_accounts.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index("ix_scheduled_posts_id", "scheduled_posts", ["id"])
    _create_index("ix_scheduled_posts_user_id", "scheduled_posts", ["user_id"])
    _create_index("ix_scheduled_posts_platform", "scheduled_posts", ["platform"])
    _create_index("ix_scheduled_posts_publish_at", "scheduled_posts", ["publish_at"])
    _create_index("ix_scheduled_posts_status", "scheduled_posts", ["status"])

    if not _has_table("activity_logs"):
        op.create_table(
            "activity_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("agent", sa.String(length=120), nullable=True),
            sa.Column("service", sa.String(length=80), nullable=False),
            sa.Column("action", sa.String(length=160), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("external_id", sa.String(length=255), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index("ix_activity_logs_id", "activity_logs", ["id"])
    _create_index("ix_activity_logs_user_id", "activity_logs", ["user_id"])
    _create_index("ix_activity_logs_service", "activity_logs", ["service"])
    _create_index("ix_activity_logs_status", "activity_logs", ["status"])

    if not _has_table("social_posts"):
        op.create_table(
            "social_posts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("platform", sa.String(length=40), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("media_url", sa.Text(), nullable=True),
            sa.Column("source", sa.String(length=80), nullable=True),
            sa.Column("run_id", sa.String(length=80), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("external_id", sa.String(length=255), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index("ix_social_posts_id", "social_posts", ["id"])
    _create_index("ix_social_posts_user_id", "social_posts", ["user_id"])
    _create_index("ix_social_posts_platform", "social_posts", ["platform"])


def downgrade() -> None:
    # This is a baseline migration for existing production data. Do not drop
    # legacy tables automatically.
    pass

