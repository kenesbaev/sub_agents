from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core_domain.schemas import AgentResponse, TeamAgentResponse, TeamResponse
from app.core_domain.seeds import DEFAULT_TEAM_DEFINITIONS, DefaultAgentDefinition, DefaultTeamDefinition
from app.models import Agent, Task, Team, TeamAgent, User, Workspace, WorkspaceMember

READ_ROLES = {"owner", "admin", "member", "viewer"}
WRITE_ROLES = {"owner", "admin", "member"}
ADMIN_ROLES = {"owner", "admin"}
WORKSPACE_ROLES = READ_ROLES
AGENT_STATUSES = {"ready", "planning", "working", "waiting", "completed", "failed", "offline"}
TASK_STATUSES = {"queued", "planning", "assigned", "in_progress", "waiting", "waiting_for_approval", "completed", "failed", "cancelled"}


@dataclass(frozen=True)
class WorkspaceContext:
    workspace: Workspace
    member: WorkspaceMember


def slugify(value: str, fallback: str = "item") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or fallback


def default_workspace_name(user: User) -> str:
    if user.first_name:
        return f"{user.first_name}'s Workspace"
    return "My Workspace"


def default_workspace_slug(user: User) -> str:
    return f"user-{user.id}-workspace"


def ensure_default_workspace(db: Session, user: User, *, seed: bool = True) -> Workspace:
    workspace = db.scalar(select(Workspace).where(Workspace.owner_id == user.id).order_by(Workspace.id))
    if not workspace:
        workspace = Workspace(
            name=default_workspace_name(user),
            slug=default_workspace_slug(user),
            owner_id=user.id,
        )
        db.add(workspace)
        db.flush()

    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if not member:
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
        db.flush()
    elif member.role != "owner" and workspace.owner_id == user.id:
        member.role = "owner"
        db.flush()

    if seed:
        seed_default_workspace(db, workspace, created_by=user.id)
    return workspace


def backfill_default_workspaces(db: Session) -> int:
    count = 0
    for user in db.scalars(select(User).order_by(User.id)).all():
        before = db.scalar(select(Workspace).where(Workspace.owner_id == user.id).order_by(Workspace.id))
        ensure_default_workspace(db, user)
        if not before:
            count += 1
    db.commit()
    return count


def get_workspace_context(db: Session, user: User, workspace_id: int | None = None) -> WorkspaceContext:
    ensure_default_workspace(db, user)
    db.flush()

    query = select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)
    if workspace_id is not None:
        query = query.where(WorkspaceMember.workspace_id == workspace_id)
    member = db.scalar(query.order_by(WorkspaceMember.id))
    if not member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace access denied")

    workspace = db.get(Workspace, member.workspace_id)
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return WorkspaceContext(workspace=workspace, member=member)


def require_workspace_role(member: WorkspaceMember, allowed_roles: set[str]) -> None:
    if member.role not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace role is not allowed")


def ensure_workspace_member(db: Session, user: User, workspace_id: int, allowed_roles: set[str] = READ_ROLES) -> WorkspaceMember:
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if not member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace access denied")
    require_workspace_role(member, allowed_roles)
    return member


def get_team_for_user(db: Session, user: User, team_id: int, allowed_roles: set[str] = READ_ROLES) -> tuple[Team, WorkspaceMember]:
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    member = ensure_workspace_member(db, user, team.workspace_id, allowed_roles)
    return team, member


def get_task_for_user(db: Session, user: User, task_id: int, allowed_roles: set[str] = READ_ROLES) -> tuple[Task, WorkspaceMember]:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    member = ensure_workspace_member(db, user, task.workspace_id, allowed_roles)
    return task, member


def ensure_agent_accessible(db: Session, workspace_id: int, agent_id: int) -> Agent:
    agent = db.get(Agent, agent_id)
    if not agent or (agent.workspace_id not in {workspace_id, None}):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


def ensure_team_accessible(db: Session, workspace_id: int, team_id: int | None) -> Team | None:
    if team_id is None:
        return None
    team = db.get(Team, team_id)
    if not team or team.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return team


def unique_team_slug(db: Session, workspace_id: int, name: str, requested_slug: str | None = None) -> str:
    base = slugify(requested_slug or name, "team")
    slug = base
    suffix = 2
    while db.scalar(select(Team.id).where(Team.workspace_id == workspace_id, Team.slug == slug)):
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _agent_description(definition: DefaultAgentDefinition, team: DefaultTeamDefinition) -> str:
    return f"{definition.role} agent for {team.name}."


def _agent_metadata(definition: DefaultAgentDefinition) -> dict[str, Any]:
    return {
        "accent": definition.accent,
    }


def _ensure_seed_agent(db: Session, workspace: Workspace, definition: DefaultAgentDefinition, team: DefaultTeamDefinition) -> Agent:
    agent = db.scalar(select(Agent).where(Agent.workspace_id == workspace.id, Agent.slug == definition.slug))
    if not agent:
        agent = Agent(
            workspace_id=workspace.id,
            slug=definition.slug,
            name=definition.name,
            role=definition.role,
            description=_agent_description(definition, team),
            avatar=definition.avatar,
            status="ready",
            is_system=False,
        )
        db.add(agent)
        db.flush()
    else:
        agent.name = agent.name or definition.name
        agent.role = agent.role or definition.role
        agent.avatar = agent.avatar or definition.avatar
        agent.status = agent.status if agent.status in AGENT_STATUSES else "ready"
    return agent


def seed_default_workspace(db: Session, workspace: Workspace, created_by: int | None = None) -> int:
    created = 0
    for team_definition in DEFAULT_TEAM_DEFINITIONS:
        seed_agents = [
            (agent_definition, _ensure_seed_agent(db, workspace, agent_definition, team_definition))
            for agent_definition in team_definition.roster
        ]
        coordinator = seed_agents[0][1] if seed_agents else None
        team = db.scalar(select(Team).where(Team.workspace_id == workspace.id, Team.slug == team_definition.slug))
        metadata = {
            **team_definition.metadata,
            "seeded": True,
            "agentsCount": team_definition.agents_count,
            "output": team_definition.output,
            "tags": list(team_definition.tags),
            "icon": team_definition.icon,
            "roster": [
                {
                    "name": agent_definition.name,
                    "role": agent_definition.role,
                    "avatar": agent_definition.avatar,
                    "accent": agent_definition.accent,
                }
                for agent_definition in team_definition.roster
            ],
        }
        if not team:
            team = Team(
                workspace_id=workspace.id,
                slug=team_definition.slug,
                name=team_definition.name,
                description=team_definition.description,
                category=team_definition.category,
                coordinator_agent_id=coordinator.id if coordinator else None,
                status="ready",
                created_by=created_by,
                metadata_json=metadata,
            )
            db.add(team)
            db.flush()
            created += 1
        else:
            team.coordinator_agent_id = team.coordinator_agent_id or (coordinator.id if coordinator else None)
            team.metadata_json = {**metadata, **(team.metadata_json or {})}

        for position, (agent_definition, agent) in enumerate(seed_agents):
            membership = db.scalar(select(TeamAgent).where(TeamAgent.team_id == team.id, TeamAgent.agent_id == agent.id))
            if not membership:
                db.add(TeamAgent(team_id=team.id, agent_id=agent.id, position=position, role_override=agent_definition.role))
                created += 1
            else:
                membership.position = position
                membership.role_override = membership.role_override or agent_definition.role
    db.flush()
    return created


def serialize_agent(agent: Agent | None) -> AgentResponse | None:
    if not agent:
        return None
    return AgentResponse(
        id=agent.id,
        workspace_id=agent.workspace_id,
        slug=agent.slug,
        name=agent.name,
        role=agent.role,
        description=agent.description,
        system_prompt=agent.system_prompt,
        provider=agent.provider,
        model=agent.model,
        avatar=agent.avatar,
        status=agent.status,
        is_system=agent.is_system,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def serialize_team_agent(db: Session, team_agent: TeamAgent) -> TeamAgentResponse:
    return TeamAgentResponse(
        id=team_agent.id,
        team_id=team_agent.team_id,
        agent_id=team_agent.agent_id,
        position=team_agent.position,
        role_override=team_agent.role_override,
        agent=serialize_agent(db.get(Agent, team_agent.agent_id)),
        created_at=team_agent.created_at,
    )


def serialize_team(db: Session, team: Team) -> TeamResponse:
    team_agents = db.scalars(select(TeamAgent).where(TeamAgent.team_id == team.id).order_by(TeamAgent.position, TeamAgent.id)).all()
    return TeamResponse(
        id=team.id,
        workspace_id=team.workspace_id,
        slug=team.slug,
        name=team.name,
        description=team.description,
        category=team.category,
        coordinator_agent_id=team.coordinator_agent_id,
        status=team.status,
        created_by=team.created_by,
        metadata_json=team.metadata_json,
        agents=[serialize_team_agent(db, team_agent) for team_agent in team_agents],
        created_at=team.created_at,
        updated_at=team.updated_at,
    )


def set_task_completion_fields(task: Task) -> None:
    now = datetime.now(UTC)
    if task.status in {"in_progress", "working"} and not task.started_at:
        task.started_at = now
    if task.status == "completed":
        task.progress = 100
        task.completed_at = task.completed_at or now
    elif task.status in {"failed", "cancelled"}:
        task.completed_at = task.completed_at or now
