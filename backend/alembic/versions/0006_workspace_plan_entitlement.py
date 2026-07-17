"""Add the workspace-level plan entitlement.

Revision ID: 0006_workspace_plan_entitlement
Revises: 0005_schema_contract_guard
Create Date: 2026-07-17
"""

from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa


revision = "0006_workspace_plan_entitlement"
down_revision = "0005_schema_contract_guard"
branch_labels = None
depends_on = None

PLAN_CHECK_NAME = "ck_workspaces_plan_code"
PLAN_CHECK_SQL = "plan_code IS NULL OR plan_code IN ('start', 'plus', 'pro', 'custom')"


def upgrade() -> None:
    if context.is_offline_mode():
        op.add_column("workspaces", sa.Column("plan_code", sa.String(length=32), nullable=True))
        op.create_check_constraint(PLAN_CHECK_NAME, "workspaces", PLAN_CHECK_SQL)
        return

    inspector = sa.inspect(op.get_bind())
    column_names = {column["name"] for column in inspector.get_columns("workspaces")}
    check_names = {
        constraint.get("name")
        for constraint in inspector.get_check_constraints("workspaces")
        if constraint.get("name")
    }

    with op.batch_alter_table("workspaces") as batch_op:
        if "plan_code" not in column_names:
            batch_op.add_column(sa.Column("plan_code", sa.String(length=32), nullable=True))
        if PLAN_CHECK_NAME not in check_names:
            batch_op.create_check_constraint(PLAN_CHECK_NAME, PLAN_CHECK_SQL)


def downgrade() -> None:
    if context.is_offline_mode():
        op.drop_constraint(PLAN_CHECK_NAME, "workspaces", type_="check")
        op.drop_column("workspaces", "plan_code")
        return

    inspector = sa.inspect(op.get_bind())
    column_names = {column["name"] for column in inspector.get_columns("workspaces")}
    check_names = {
        constraint.get("name")
        for constraint in inspector.get_check_constraints("workspaces")
        if constraint.get("name")
    }

    with op.batch_alter_table("workspaces") as batch_op:
        if PLAN_CHECK_NAME in check_names:
            batch_op.drop_constraint(PLAN_CHECK_NAME, type_="check")
        if "plan_code" in column_names:
            batch_op.drop_column("plan_code")
