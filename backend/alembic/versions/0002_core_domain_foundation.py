"""Add workspace, agent, team, and task foundation.

Revision ID: 0002_core_domain_foundation
Revises: 0001_existing_schema_baseline
Create Date: 2026-07-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_core_domain_foundation"
down_revision = "0001_existing_schema_baseline"
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
    if not _has_table("workspaces"):
        op.create_table(
            "workspaces",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("slug", sa.String(length=180), nullable=False),
            sa.Column("owner_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug", name="uq_workspaces_slug"),
        )
    _create_index("ix_workspaces_id", "workspaces", ["id"])
    _create_index("ix_workspaces_slug", "workspaces", ["slug"])
    _create_index("ix_workspaces_owner_id", "workspaces", ["owner_id"])

    if not _has_table("workspace_members"):
        op.create_table(
            "workspace_members",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=40), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),
        )
    _create_index("ix_workspace_members_id", "workspace_members", ["id"])
    _create_index("ix_workspace_members_workspace_id", "workspace_members", ["workspace_id"])
    _create_index("ix_workspace_members_user_id", "workspace_members", ["user_id"])
    _create_index("ix_workspace_members_user_role", "workspace_members", ["user_id", "role"])

    if not _has_table("agents"):
        op.create_table(
            "agents",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=True),
            sa.Column("slug", sa.String(length=120), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("role", sa.String(length=160), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("system_prompt", sa.Text(), nullable=True),
            sa.Column("provider", sa.String(length=80), nullable=True),
            sa.Column("model", sa.String(length=120), nullable=True),
            sa.Column("avatar", sa.String(length=500), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("is_system", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("workspace_id", "slug", name="uq_agents_workspace_slug"),
        )
    _create_index("ix_agents_id", "agents", ["id"])
    _create_index("ix_agents_workspace_id", "agents", ["workspace_id"])
    _create_index("ix_agents_slug", "agents", ["slug"])
    _create_index("ix_agents_status", "agents", ["status"])
    _create_index("ix_agents_workspace_status", "agents", ["workspace_id", "status"])
    _create_index("ix_agents_is_system", "agents", ["is_system"])

    if not _has_table("teams"):
        op.create_table(
            "teams",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=False),
            sa.Column("slug", sa.String(length=120), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("category", sa.String(length=120), nullable=True),
            sa.Column("coordinator_agent_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["coordinator_agent_id"], ["agents.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("workspace_id", "slug", name="uq_teams_workspace_slug"),
        )
    _create_index("ix_teams_id", "teams", ["id"])
    _create_index("ix_teams_workspace_id", "teams", ["workspace_id"])
    _create_index("ix_teams_status", "teams", ["status"])
    _create_index("ix_teams_created_by", "teams", ["created_by"])
    _create_index("ix_teams_workspace_status", "teams", ["workspace_id", "status"])
    _create_index("ix_teams_workspace_category", "teams", ["workspace_id", "category"])

    if not _has_table("team_agents"):
        op.create_table(
            "team_agents",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("team_id", sa.Integer(), nullable=False),
            sa.Column("agent_id", sa.Integer(), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("role_override", sa.String(length=160), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("team_id", "agent_id", name="uq_team_agents_team_agent"),
        )
    _create_index("ix_team_agents_id", "team_agents", ["id"])
    _create_index("ix_team_agents_team_id", "team_agents", ["team_id"])
    _create_index("ix_team_agents_agent_id", "team_agents", ["agent_id"])
    _create_index("ix_team_agents_team_position", "team_agents", ["team_id", "position"])

    if not _has_table("tasks"):
        op.create_table(
            "tasks",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=False),
            sa.Column("team_id", sa.Integer(), nullable=True),
            sa.Column("assigned_agent_id", sa.Integer(), nullable=True),
            sa.Column("parent_task_id", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("priority", sa.String(length=40), nullable=False),
            sa.Column("progress", sa.Integer(), nullable=False),
            sa.Column("input_json", sa.JSON(), nullable=True),
            sa.Column("result_json", sa.JSON(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["assigned_agent_id"], ["agents.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["parent_task_id"], ["tasks.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index("ix_tasks_id", "tasks", ["id"])
    _create_index("ix_tasks_workspace_id", "tasks", ["workspace_id"])
    _create_index("ix_tasks_team_id", "tasks", ["team_id"])
    _create_index("ix_tasks_assigned_agent_id", "tasks", ["assigned_agent_id"])
    _create_index("ix_tasks_parent_task_id", "tasks", ["parent_task_id"])
    _create_index("ix_tasks_status", "tasks", ["status"])
    _create_index("ix_tasks_priority", "tasks", ["priority"])
    _create_index("ix_tasks_created_by", "tasks", ["created_by"])
    _create_index("ix_tasks_workspace_status", "tasks", ["workspace_id", "status"])
    _create_index("ix_tasks_workspace_priority", "tasks", ["workspace_id", "priority"])
    _create_index("ix_tasks_team_status", "tasks", ["team_id", "status"])

    _backfill_default_workspaces()


def _backfill_default_workspaces() -> None:
    bind = op.get_bind()
    users = bind.execute(sa.text("SELECT id, first_name FROM users ORDER BY id")).mappings().all()
    for user in users:
        workspace = bind.execute(
            sa.text("SELECT id FROM workspaces WHERE owner_id = :owner_id ORDER BY id LIMIT 1"),
            {"owner_id": user["id"]},
        ).mappings().first()
        if workspace:
            workspace_id = workspace["id"]
        else:
            name = f"{user['first_name']}'s Workspace" if user["first_name"] else "My Workspace"
            slug = f"user-{user['id']}-workspace"
            bind.execute(
                sa.text("INSERT INTO workspaces (name, slug, owner_id) VALUES (:name, :slug, :owner_id)"),
                {"name": name, "slug": slug, "owner_id": user["id"]},
            )
            workspace_id = bind.execute(
                sa.text("SELECT id FROM workspaces WHERE slug = :slug"),
                {"slug": slug},
            ).scalar_one()
        member = bind.execute(
            sa.text("SELECT id FROM workspace_members WHERE workspace_id = :workspace_id AND user_id = :user_id"),
            {"workspace_id": workspace_id, "user_id": user["id"]},
        ).first()
        if not member:
            bind.execute(
                sa.text(
                    "INSERT INTO workspace_members (workspace_id, user_id, role) "
                    "VALUES (:workspace_id, :user_id, 'owner')"
                ),
                {"workspace_id": workspace_id, "user_id": user["id"]},
            )


def downgrade() -> None:
    op.drop_table("tasks")
    op.drop_table("team_agents")
    op.drop_table("teams")
    op.drop_table("agents")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")

