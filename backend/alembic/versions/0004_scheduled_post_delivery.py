"""Add safe scheduled-post delivery claims.

Revision ID: 0004_scheduled_post_delivery
Revises: 0003_youtube_growth_agent
Create Date: 2026-07-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.connected_apps.providers import PROVIDERS


revision = "0004_scheduled_post_delivery"
down_revision = "0003_youtube_growth_agent"
branch_labels = None
depends_on = None


def _column_names() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns("scheduled_posts")}


def _index_names() -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("scheduled_posts")}


def _unique_names(table_name: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table_name)
        if constraint.get("name")
    }


def _assert_connected_apps_are_unique() -> None:
    """Abort before mutation when legacy rows need a reviewed data merge.

    Automatically choosing a duplicate account or token can delete or detach
    scheduled posts and YouTube history through foreign-key actions.  A backup
    plus an account-by-account merge is safer than guessing inside a schema
    migration.
    """

    bind = op.get_bind()
    duplicate_checks = (
        (
            "user_integrations(user_id, provider_id)",
            "SELECT 1 FROM user_integrations GROUP BY user_id, provider_id HAVING COUNT(*) > 1 LIMIT 1",
        ),
        (
            "integration_accounts(user_integration_id, account_identifier)",
            "SELECT 1 FROM integration_accounts GROUP BY user_integration_id, account_identifier "
            "HAVING COUNT(*) > 1 LIMIT 1",
        ),
        (
            "integration_tokens(user_integration_id, integration_account_id)",
            "SELECT 1 FROM integration_tokens GROUP BY user_integration_id, integration_account_id "
            "HAVING COUNT(*) > 1 LIMIT 1",
        ),
        (
            "integration_capabilities(provider_id, key)",
            "SELECT 1 FROM integration_capabilities GROUP BY provider_id, key HAVING COUNT(*) > 1 LIMIT 1",
        ),
    )
    duplicates = [label for label, query in duplicate_checks if bind.execute(sa.text(query)).first()]
    if duplicates:
        raise RuntimeError(
            "Migration 0004 stopped before modifying data: duplicate Connected Apps rows exist in "
            + ", ".join(duplicates)
            + ". Back up the database and merge these rows with an account-specific reviewed data migration."
        )


def _seed_provider_registry() -> None:
    """Make cold multi-replica startup read-only for the current registry."""
    bind = op.get_bind()
    for definition in PROVIDERS.values():
        provider_id = bind.execute(
            sa.text("SELECT id FROM integration_providers WHERE key = :key"),
            {"key": definition.key},
        ).scalar_one_or_none()
        provider_values = {
            "key": definition.key,
            "name": definition.name,
            "auth_type": definition.auth_type,
            "logo": definition.logo,
            "docs_url": definition.docs_url,
        }
        if provider_id is None:
            bind.execute(
                sa.text(
                    "INSERT INTO integration_providers (key, name, auth_type, logo, docs_url) "
                    "VALUES (:key, :name, :auth_type, :logo, :docs_url)"
                ),
                provider_values,
            )
            provider_id = bind.execute(
                sa.text("SELECT id FROM integration_providers WHERE key = :key"),
                {"key": definition.key},
            ).scalar_one()
        else:
            bind.execute(
                sa.text(
                    "UPDATE integration_providers SET name = :name, auth_type = :auth_type, "
                    "logo = :logo, docs_url = :docs_url WHERE id = :provider_id"
                ),
                {**provider_values, "provider_id": provider_id},
            )

        for capability in definition.capabilities:
            capability_id = bind.execute(
                sa.text(
                    "SELECT id FROM integration_capabilities "
                    "WHERE provider_id = :provider_id AND key = :key"
                ),
                {"provider_id": provider_id, "key": capability.key},
            ).scalar_one_or_none()
            values = {
                "provider_id": provider_id,
                "key": capability.key,
                "name": capability.name,
                "description": capability.description,
                "scope": capability.scope,
                "access_level": capability.access_level,
            }
            if capability_id is None:
                bind.execute(
                    sa.text(
                        "INSERT INTO integration_capabilities "
                        "(provider_id, key, name, description, scope, access_level) "
                        "VALUES (:provider_id, :key, :name, :description, :scope, :access_level)"
                    ),
                    values,
                )
            else:
                bind.execute(
                    sa.text(
                        "UPDATE integration_capabilities SET name = :name, description = :description, "
                        "scope = :scope, access_level = :access_level WHERE id = :capability_id"
                    ),
                    {**values, "capability_id": capability_id},
                )


def upgrade() -> None:
    _assert_connected_apps_are_unique()
    columns = _column_names()
    if "next_attempt_at" not in columns:
        op.add_column("scheduled_posts", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    if "claimed_at" not in columns:
        op.add_column("scheduled_posts", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    if "claim_token" not in columns:
        op.add_column("scheduled_posts", sa.Column("claim_token", sa.String(length=96), nullable=True))

    indexes = _index_names()
    if "ix_scheduled_posts_due" not in indexes:
        op.create_index(
            "ix_scheduled_posts_due",
            "scheduled_posts",
            ["status", "next_attempt_at", "publish_at"],
        )
    if "ix_scheduled_posts_stale_claim" not in indexes:
        op.create_index(
            "ix_scheduled_posts_stale_claim",
            "scheduled_posts",
            ["status", "claimed_at"],
        )

    _seed_provider_registry()
    constraints = (
        (
            "user_integrations",
            "uq_user_integrations_user_provider",
            ["user_id", "provider_id"],
        ),
        (
            "integration_accounts",
            "uq_integration_accounts_integration_identifier",
            ["user_integration_id", "account_identifier"],
        ),
        (
            "integration_tokens",
            "uq_integration_tokens_integration_account",
            ["user_integration_id", "integration_account_id"],
        ),
        (
            "integration_capabilities",
            "uq_integration_capabilities_provider_key",
            ["provider_id", "key"],
        ),
    )
    for table_name, constraint_name, columns in constraints:
        if constraint_name not in _unique_names(table_name):
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.create_unique_constraint(constraint_name, columns)


def downgrade() -> None:
    constraints = (
        ("integration_capabilities", "uq_integration_capabilities_provider_key"),
        ("integration_tokens", "uq_integration_tokens_integration_account"),
        ("integration_accounts", "uq_integration_accounts_integration_identifier"),
        ("user_integrations", "uq_user_integrations_user_provider"),
    )
    for table_name, constraint_name in constraints:
        if constraint_name in _unique_names(table_name):
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.drop_constraint(constraint_name, type_="unique")
    indexes = _index_names()
    if "ix_scheduled_posts_stale_claim" in indexes:
        op.drop_index("ix_scheduled_posts_stale_claim", table_name="scheduled_posts")
    if "ix_scheduled_posts_due" in indexes:
        op.drop_index("ix_scheduled_posts_due", table_name="scheduled_posts")
    columns = _column_names()
    if "claim_token" in columns:
        op.drop_column("scheduled_posts", "claim_token")
    if "claimed_at" in columns:
        op.drop_column("scheduled_posts", "claimed_at")
    if "next_attempt_at" in columns:
        op.drop_column("scheduled_posts", "next_attempt_at")
