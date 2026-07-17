"""Fail closed when an adopted legacy database is structurally incomplete.

Revision ID: 0005_schema_contract_guard
Revises: 0004_scheduled_post_delivery
Create Date: 2026-07-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_schema_contract_guard"
down_revision = "0004_scheduled_post_delivery"
branch_labels = None
depends_on = None


def _columns(value: str) -> frozenset[str]:
    return frozenset(value.split())


# This is deliberately a frozen snapshot of the schema at revision 0005.
# Importing current ORM metadata here would make every future model addition
# appear required before the migration that actually creates it runs.
SCHEMA_CONTRACT_0005 = {
    "users": _columns("id email hashed_password google_sub first_name last_name avatar_url created_at"),
    "workspaces": _columns("id name slug owner_id created_at updated_at"),
    "workspace_members": _columns("id workspace_id user_id role created_at updated_at"),
    "agents": _columns(
        "id workspace_id slug name role description system_prompt provider model avatar status is_system created_at updated_at"
    ),
    "teams": _columns(
        "id workspace_id slug name description category coordinator_agent_id status created_by metadata_json created_at updated_at"
    ),
    "team_agents": _columns("id team_id agent_id position role_override created_at"),
    "tasks": _columns(
        "id workspace_id team_id assigned_agent_id parent_task_id title description status priority progress input_json "
        "result_json error created_by created_at started_at completed_at updated_at"
    ),
    "telegram_bot_integrations": _columns(
        "id user_id encrypted_bot_token target_chat_id bot_username created_at updated_at"
    ),
    "instagram_integrations": _columns(
        "id user_id encrypted_access_token ig_user_id username created_at updated_at"
    ),
    "integration_providers": _columns("id key name auth_type logo docs_url created_at updated_at"),
    "user_integrations": _columns(
        "id user_id provider_id status connected_at disconnected_at last_error created_at updated_at"
    ),
    "integration_accounts": _columns(
        "id user_integration_id provider_id account_identifier account_label account_type is_default metadata_json "
        "created_at updated_at"
    ),
    "integration_tokens": _columns(
        "id user_integration_id integration_account_id encrypted_access_token encrypted_refresh_token token_type "
        "expires_at scopes created_at updated_at"
    ),
    "integration_capabilities": _columns(
        "id provider_id key name description scope access_level created_at"
    ),
    "scheduled_posts": _columns(
        "id user_id platform account_id content media_url media_type publish_at timezone repeat_rule status source run_id "
        "external_id error attempts next_attempt_at claimed_at claim_token created_at updated_at"
    ),
    "activity_logs": _columns(
        "id user_id agent service action status external_id error metadata_json created_at"
    ),
    "social_posts": _columns(
        "id user_id platform text media_url source run_id status external_id error created_at"
    ),
    "youtube_analysis_runs": _columns(
        "id workspace_id created_by task_id integration_account_id kind target_id target_url status request_json result_json "
        "limitations_json partial error_code error idempotency_key created_at updated_at completed_at"
    ),
    "youtube_analysis_sources": _columns(
        "id workspace_id analysis_id source_type external_id url title published_at timestamp_seconds fact facts_json created_at"
    ),
    "youtube_content_plans": _columns(
        "id workspace_id created_by task_id source_analysis_id integration_account_id horizon_days niche language region goal "
        "status request_json result_json limitations_json model_name repair_attempts idempotency_key error created_at updated_at "
        "completed_at"
    ),
    "youtube_content_plan_items": _columns(
        "id workspace_id plan_id position publish_date item_json score_components_json opportunity_score confidence approved "
        "created_at updated_at"
    ),
    "youtube_growth_snapshots": _columns(
        "id workspace_id created_by task_id integration_account_id video_id checkpoint status metrics_json baseline_json "
        "recommendations_json limitations_json error_code error scheduled_for observed_at created_at updated_at"
    ),
    "youtube_api_cache": _columns(
        "id cache_key namespace workspace_id integration_account_id response_json expires_at quota_cost created_at updated_at"
    ),
}


CRITICAL_UNIQUE_CONSTRAINTS = {
    "user_integrations": "uq_user_integrations_user_provider",
    "integration_accounts": "uq_integration_accounts_integration_identifier",
    "integration_tokens": "uq_integration_tokens_integration_account",
    "integration_capabilities": "uq_integration_capabilities_provider_key",
}


def upgrade() -> None:
    """Validate the schema created or adopted by all earlier revisions."""
    inspector = sa.inspect(op.get_bind())
    errors: list[str] = []
    for table_name, required_columns in SCHEMA_CONTRACT_0005.items():
        if not inspector.has_table(table_name):
            errors.append(f"missing table {table_name}")
            continue
        actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
        missing_columns = required_columns - actual_columns
        if missing_columns:
            errors.append(f"{table_name} missing columns: {', '.join(sorted(missing_columns))}")

    for table_name, constraint_name in CRITICAL_UNIQUE_CONSTRAINTS.items():
        if not inspector.has_table(table_name):
            continue
        actual_names = {
            item.get("name")
            for item in inspector.get_unique_constraints(table_name)
            if item.get("name")
        }
        if constraint_name not in actual_names:
            errors.append(f"{table_name} missing unique constraint {constraint_name}")

    if errors:
        detail = "; ".join(errors[:25])
        raise RuntimeError(
            "Database schema contract validation failed. Restore a backup into staging and reconcile schema drift: "
            + detail
        )


def downgrade() -> None:
    # This revision is validation-only and never mutates application data.
    pass
