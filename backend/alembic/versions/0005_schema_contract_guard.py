"""Fail closed when an adopted legacy database is structurally incomplete.

Revision ID: 0005_schema_contract_guard
Revises: 0004_scheduled_post_delivery
Create Date: 2026-07-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app import models  # noqa: F401 - registers every ORM table
from app.db.base import Base


revision = "0005_schema_contract_guard"
down_revision = "0004_scheduled_post_delivery"
branch_labels = None
depends_on = None


CRITICAL_UNIQUE_CONSTRAINTS = {
    "user_integrations": "uq_user_integrations_user_provider",
    "integration_accounts": "uq_integration_accounts_integration_identifier",
    "integration_tokens": "uq_integration_tokens_integration_account",
    "integration_capabilities": "uq_integration_capabilities_provider_key",
}
models.User.__table__  # register and statically reference all ORM tables


def upgrade() -> None:
    """Validate the schema created or adopted by all earlier revisions."""
    inspector = sa.inspect(op.get_bind())
    errors: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        if not inspector.has_table(table_name):
            errors.append(f"missing table {table_name}")
            continue
        actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
        missing_columns = set(table.columns.keys()) - actual_columns
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
