"""Add workspace-scoped YouTube Growth Agent artifacts.

Revision ID: 0003_youtube_growth_agent
Revises: 0002_core_domain_foundation
Create Date: 2026-07-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_youtube_growth_agent"
down_revision = "0002_core_domain_foundation"
branch_labels = None
depends_on = None


EXPECTED_TABLE_COLUMNS = {
    "youtube_analysis_runs": {
        "id", "workspace_id", "created_by", "task_id", "integration_account_id", "kind", "target_id",
        "target_url", "status", "request_json", "result_json", "limitations_json", "partial", "error_code",
        "error", "idempotency_key", "created_at", "updated_at", "completed_at",
    },
    "youtube_analysis_sources": {
        "id", "workspace_id", "analysis_id", "source_type", "external_id", "url", "title", "published_at",
        "timestamp_seconds", "fact", "facts_json", "created_at",
    },
    "youtube_content_plans": {
        "id", "workspace_id", "created_by", "task_id", "source_analysis_id", "integration_account_id",
        "horizon_days", "niche", "language", "region", "goal", "status", "request_json", "result_json",
        "limitations_json", "model_name", "repair_attempts", "idempotency_key", "error", "created_at",
        "updated_at", "completed_at",
    },
    "youtube_content_plan_items": {
        "id", "workspace_id", "plan_id", "position", "publish_date", "item_json", "score_components_json",
        "opportunity_score", "confidence", "approved", "created_at", "updated_at",
    },
    "youtube_growth_snapshots": {
        "id", "workspace_id", "created_by", "task_id", "integration_account_id", "video_id", "checkpoint",
        "status", "metrics_json", "baseline_json", "recommendations_json", "limitations_json", "error_code",
        "error", "scheduled_for", "observed_at", "created_at", "updated_at",
    },
    "youtube_api_cache": {
        "id", "cache_key", "namespace", "workspace_id", "integration_account_id", "response_json",
        "expires_at", "quota_cost", "created_at", "updated_at",
    },
}


def _validate_preexisting_schema() -> bool:
    """Accept only a complete ORM-created schema; reject ambiguous partial state."""
    inspector = sa.inspect(op.get_bind())
    existing = {table for table in EXPECTED_TABLE_COLUMNS if inspector.has_table(table)}
    if not existing:
        return False
    expected = set(EXPECTED_TABLE_COLUMNS)
    if existing != expected:
        missing = ", ".join(sorted(expected - existing))
        raise RuntimeError(
            "Partial YouTube Growth schema detected. Restore from backup or reconcile it before retrying; "
            f"missing tables: {missing}"
        )
    for table, expected_columns in EXPECTED_TABLE_COLUMNS.items():
        actual_columns = {column["name"] for column in inspector.get_columns(table)}
        missing_columns = expected_columns - actual_columns
        if missing_columns:
            raise RuntimeError(
                f"Existing table {table!r} is incompatible; missing columns: {', '.join(sorted(missing_columns))}"
            )
    return True


def upgrade() -> None:
    # Older local installations created these tables through ORM create_all()
    # before this revision existed. A complete compatible set is preserved;
    # a partial or incompatible set fails closed instead of risking data loss.
    if _validate_preexisting_schema():
        return

    op.create_table(
        "youtube_analysis_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("integration_account_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=True),
        sa.Column("target_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("limitations_json", sa.JSON(), nullable=True),
        sa.Column("partial", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["integration_account_id"], ["integration_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_youtube_analysis_workspace_idempotency"),
    )
    op.create_index("ix_youtube_analysis_runs_id", "youtube_analysis_runs", ["id"])
    op.create_index("ix_youtube_analysis_runs_workspace_id", "youtube_analysis_runs", ["workspace_id"])
    op.create_index("ix_youtube_analysis_runs_created_by", "youtube_analysis_runs", ["created_by"])
    op.create_index("ix_youtube_analysis_runs_task_id", "youtube_analysis_runs", ["task_id"])
    op.create_index("ix_youtube_analysis_runs_integration_account_id", "youtube_analysis_runs", ["integration_account_id"])
    op.create_index("ix_youtube_analysis_runs_kind", "youtube_analysis_runs", ["kind"])
    op.create_index("ix_youtube_analysis_runs_target_id", "youtube_analysis_runs", ["target_id"])
    op.create_index("ix_youtube_analysis_runs_status", "youtube_analysis_runs", ["status"])
    op.create_index("ix_youtube_analysis_workspace_status", "youtube_analysis_runs", ["workspace_id", "status"])
    op.create_index("ix_youtube_analysis_workspace_kind", "youtube_analysis_runs", ["workspace_id", "kind"])

    op.create_table(
        "youtube_analysis_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("analysis_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timestamp_seconds", sa.Integer(), nullable=True),
        sa.Column("fact", sa.Text(), nullable=True),
        sa.Column("facts_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["youtube_analysis_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_youtube_analysis_sources_id", "youtube_analysis_sources", ["id"])
    op.create_index("ix_youtube_analysis_sources_workspace_id", "youtube_analysis_sources", ["workspace_id"])
    op.create_index("ix_youtube_analysis_sources_analysis_id", "youtube_analysis_sources", ["analysis_id"])
    op.create_index("ix_youtube_analysis_sources_external_id", "youtube_analysis_sources", ["external_id"])
    op.create_index("ix_youtube_sources_workspace_analysis", "youtube_analysis_sources", ["workspace_id", "analysis_id"])
    op.create_index("ix_youtube_sources_external", "youtube_analysis_sources", ["source_type", "external_id"])

    op.create_table(
        "youtube_content_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("source_analysis_id", sa.Integer(), nullable=True),
        sa.Column("integration_account_id", sa.Integer(), nullable=True),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("niche", sa.String(length=300), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("region", sa.String(length=100), nullable=False),
        sa.Column("goal", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("limitations_json", sa.JSON(), nullable=True),
        sa.Column("model_name", sa.String(length=160), nullable=True),
        sa.Column("repair_attempts", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["integration_account_id"], ["integration_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_analysis_id"], ["youtube_analysis_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_youtube_plan_workspace_idempotency"),
    )
    op.create_index("ix_youtube_content_plans_id", "youtube_content_plans", ["id"])
    op.create_index("ix_youtube_content_plans_workspace_id", "youtube_content_plans", ["workspace_id"])
    op.create_index("ix_youtube_content_plans_created_by", "youtube_content_plans", ["created_by"])
    op.create_index("ix_youtube_content_plans_task_id", "youtube_content_plans", ["task_id"])
    op.create_index("ix_youtube_content_plans_source_analysis_id", "youtube_content_plans", ["source_analysis_id"])
    op.create_index("ix_youtube_content_plans_integration_account_id", "youtube_content_plans", ["integration_account_id"])
    op.create_index("ix_youtube_content_plans_status", "youtube_content_plans", ["status"])
    op.create_index("ix_youtube_plans_workspace_status", "youtube_content_plans", ["workspace_id", "status"])

    op.create_table(
        "youtube_content_plan_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("publish_date", sa.String(length=10), nullable=False),
        sa.Column("item_json", sa.JSON(), nullable=False),
        sa.Column("score_components_json", sa.JSON(), nullable=False),
        sa.Column("opportunity_score", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.String(length=20), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["youtube_content_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "position", name="uq_youtube_plan_items_position"),
    )
    op.create_index("ix_youtube_content_plan_items_id", "youtube_content_plan_items", ["id"])
    op.create_index("ix_youtube_content_plan_items_workspace_id", "youtube_content_plan_items", ["workspace_id"])
    op.create_index("ix_youtube_content_plan_items_plan_id", "youtube_content_plan_items", ["plan_id"])
    op.create_index("ix_youtube_content_plan_items_publish_date", "youtube_content_plan_items", ["publish_date"])
    op.create_index("ix_youtube_plan_items_workspace_date", "youtube_content_plan_items", ["workspace_id", "publish_date"])

    op.create_table(
        "youtube_growth_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("integration_account_id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.String(length=64), nullable=False),
        sa.Column("checkpoint", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=True),
        sa.Column("baseline_json", sa.JSON(), nullable=True),
        sa.Column("recommendations_json", sa.JSON(), nullable=True),
        sa.Column("limitations_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["integration_account_id"], ["integration_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "integration_account_id", "video_id", "checkpoint", name="uq_youtube_snapshot_workspace_account_video_checkpoint"),
    )
    op.create_index("ix_youtube_growth_snapshots_id", "youtube_growth_snapshots", ["id"])
    op.create_index("ix_youtube_growth_snapshots_workspace_id", "youtube_growth_snapshots", ["workspace_id"])
    op.create_index("ix_youtube_growth_snapshots_created_by", "youtube_growth_snapshots", ["created_by"])
    op.create_index("ix_youtube_growth_snapshots_task_id", "youtube_growth_snapshots", ["task_id"])
    op.create_index("ix_youtube_growth_snapshots_integration_account_id", "youtube_growth_snapshots", ["integration_account_id"])
    op.create_index("ix_youtube_growth_snapshots_video_id", "youtube_growth_snapshots", ["video_id"])
    op.create_index("ix_youtube_growth_snapshots_status", "youtube_growth_snapshots", ["status"])
    op.create_index("ix_youtube_snapshots_workspace_video", "youtube_growth_snapshots", ["workspace_id", "video_id"])

    op.create_table(
        "youtube_api_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("namespace", sa.String(length=80), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=True),
        sa.Column("integration_account_id", sa.Integer(), nullable=True),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quota_cost", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["integration_account_id"], ["integration_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_youtube_api_cache_id", "youtube_api_cache", ["id"])
    op.create_index("ix_youtube_api_cache_cache_key", "youtube_api_cache", ["cache_key"], unique=True)
    op.create_index("ix_youtube_api_cache_workspace_id", "youtube_api_cache", ["workspace_id"])
    op.create_index("ix_youtube_api_cache_integration_account_id", "youtube_api_cache", ["integration_account_id"])
    op.create_index("ix_youtube_api_cache_expires_at", "youtube_api_cache", ["expires_at"])
    op.create_index("ix_youtube_cache_namespace_expiry", "youtube_api_cache", ["namespace", "expires_at"])
    op.create_index("ix_youtube_cache_workspace", "youtube_api_cache", ["workspace_id", "integration_account_id"])


def downgrade() -> None:
    op.drop_table("youtube_api_cache")
    op.drop_table("youtube_growth_snapshots")
    op.drop_table("youtube_content_plan_items")
    op.drop_table("youtube_content_plans")
    op.drop_table("youtube_analysis_sources")
    op.drop_table("youtube_analysis_runs")
