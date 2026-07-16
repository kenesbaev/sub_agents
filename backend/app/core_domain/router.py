from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core_domain.schemas import (
    DeleteResponse,
    TaskCreateRequest,
    TaskResponse,
    TaskUpdateRequest,
    TeamAgentCreateRequest,
    TeamAgentResponse,
    TeamCreateRequest,
    TeamResponse,
    TeamUpdateRequest,
)
from app.core_domain.service import (
    ADMIN_ROLES,
    READ_ROLES,
    WRITE_ROLES,
    ensure_agent_accessible,
    ensure_team_accessible,
    get_task_for_user,
    get_team_for_user,
    get_workspace_context,
    require_workspace_role,
    serialize_agent,
    serialize_team,
    set_task_completion_fields,
    unique_team_slug,
)
from app.db.session import get_db
from app.models import Task, Team, TeamAgent, User
from app.security import get_current_user

router = APIRouter(tags=["core-domain"])


def serialize_task(task: Task) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        workspace_id=task.workspace_id,
        team_id=task.team_id,
        assigned_agent_id=task.assigned_agent_id,
        parent_task_id=task.parent_task_id,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        progress=task.progress,
        input_json=task.input_json,
        result_json=task.result_json,
        error=task.error,
        created_by=task.created_by,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        updated_at=task.updated_at,
    )


@router.get("/api/teams", response_model=list[TeamResponse])
def list_teams(
    workspace_id: int | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TeamResponse]:
    context = get_workspace_context(db, user, workspace_id)
    db.commit()
    teams = db.scalars(select(Team).where(Team.workspace_id == context.workspace.id).order_by(Team.id)).all()
    return [serialize_team(db, team) for team in teams]


@router.get("/api/teams/{team_id}", response_model=TeamResponse)
def get_team(team_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TeamResponse:
    team, _member = get_team_for_user(db, user, team_id, READ_ROLES)
    return serialize_team(db, team)


@router.post("/api/teams", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
def create_team(
    payload: TeamCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TeamResponse:
    context = get_workspace_context(db, user, payload.workspace_id)
    require_workspace_role(context.member, ADMIN_ROLES)
    coordinator = ensure_agent_accessible(db, context.workspace.id, payload.coordinator_agent_id) if payload.coordinator_agent_id else None
    team = Team(
        workspace_id=context.workspace.id,
        slug=unique_team_slug(db, context.workspace.id, payload.name, payload.slug),
        name=payload.name,
        description=payload.description,
        category=payload.category,
        coordinator_agent_id=coordinator.id if coordinator else None,
        status=payload.status,
        created_by=user.id,
        metadata_json=payload.metadata_json,
    )
    db.add(team)
    db.commit()
    db.refresh(team)
    return serialize_team(db, team)


@router.patch("/api/teams/{team_id}", response_model=TeamResponse)
def update_team(
    team_id: int,
    payload: TeamUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TeamResponse:
    team, member = get_team_for_user(db, user, team_id, ADMIN_ROLES)
    require_workspace_role(member, ADMIN_ROLES)
    updates = payload.model_dump(exclude_unset=True)
    if "coordinator_agent_id" in updates and updates["coordinator_agent_id"] is not None:
        ensure_agent_accessible(db, team.workspace_id, updates["coordinator_agent_id"])
    for field, value in updates.items():
        setattr(team, field, value)
    db.commit()
    db.refresh(team)
    return serialize_team(db, team)


@router.delete("/api/teams/{team_id}", response_model=DeleteResponse)
def delete_team(team_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DeleteResponse:
    team, member = get_team_for_user(db, user, team_id, ADMIN_ROLES)
    require_workspace_role(member, ADMIN_ROLES)
    db.delete(team)
    db.commit()
    return DeleteResponse()


@router.post("/api/teams/{team_id}/agents", response_model=TeamAgentResponse, status_code=status.HTTP_201_CREATED)
def add_team_agent(
    team_id: int,
    payload: TeamAgentCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TeamAgentResponse:
    team, member = get_team_for_user(db, user, team_id, ADMIN_ROLES)
    require_workspace_role(member, ADMIN_ROLES)
    agent = ensure_agent_accessible(db, team.workspace_id, payload.agent_id)
    membership = db.scalar(select(TeamAgent).where(TeamAgent.team_id == team.id, TeamAgent.agent_id == agent.id))
    if not membership:
        membership = TeamAgent(
            team_id=team.id,
            agent_id=agent.id,
            position=payload.position,
            role_override=payload.role_override,
        )
        db.add(membership)
    else:
        membership.position = payload.position
        membership.role_override = payload.role_override
    db.commit()
    db.refresh(membership)
    return TeamAgentResponse(
        id=membership.id,
        team_id=membership.team_id,
        agent_id=membership.agent_id,
        position=membership.position,
        role_override=membership.role_override,
        agent=serialize_agent(agent),
        created_at=membership.created_at,
    )


@router.delete("/api/teams/{team_id}/agents/{agent_id}", response_model=DeleteResponse)
def remove_team_agent(
    team_id: int,
    agent_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DeleteResponse:
    team, member = get_team_for_user(db, user, team_id, ADMIN_ROLES)
    require_workspace_role(member, ADMIN_ROLES)
    db.execute(delete(TeamAgent).where(TeamAgent.team_id == team.id, TeamAgent.agent_id == agent_id))
    db.commit()
    return DeleteResponse()


@router.get("/api/tasks", response_model=list[TaskResponse])
def list_tasks(
    workspace_id: int | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TaskResponse]:
    context = get_workspace_context(db, user, workspace_id)
    db.commit()
    tasks = db.scalars(select(Task).where(Task.workspace_id == context.workspace.id).order_by(Task.created_at.desc(), Task.id.desc())).all()
    return [serialize_task(task) for task in tasks]


@router.get("/api/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TaskResponse:
    task, _member = get_task_for_user(db, user, task_id, READ_ROLES)
    return serialize_task(task)


@router.post("/api/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskResponse:
    context = get_workspace_context(db, user, payload.workspace_id)
    require_workspace_role(context.member, WRITE_ROLES)
    ensure_team_accessible(db, context.workspace.id, payload.team_id)
    if payload.assigned_agent_id is not None:
        ensure_agent_accessible(db, context.workspace.id, payload.assigned_agent_id)
    if payload.parent_task_id is not None:
        parent, _member = get_task_for_user(db, user, payload.parent_task_id, READ_ROLES)
        if parent.workspace_id != context.workspace.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Parent task is outside this workspace")
    task = Task(
        workspace_id=context.workspace.id,
        team_id=payload.team_id,
        assigned_agent_id=payload.assigned_agent_id,
        parent_task_id=payload.parent_task_id,
        title=payload.title,
        description=payload.description,
        status=payload.status,
        priority=payload.priority,
        progress=payload.progress,
        input_json=payload.input_json,
        created_by=user.id,
    )
    set_task_completion_fields(task)
    db.add(task)
    db.commit()
    db.refresh(task)
    return serialize_task(task)


@router.patch("/api/tasks/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: int,
    payload: TaskUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskResponse:
    task, member = get_task_for_user(db, user, task_id, WRITE_ROLES)
    require_workspace_role(member, WRITE_ROLES)
    updates = payload.model_dump(exclude_unset=True)
    if "team_id" in updates:
        ensure_team_accessible(db, task.workspace_id, updates["team_id"])
    if updates.get("assigned_agent_id") is not None:
        ensure_agent_accessible(db, task.workspace_id, updates["assigned_agent_id"])
    if updates.get("parent_task_id") is not None:
        parent, _member = get_task_for_user(db, user, updates["parent_task_id"], READ_ROLES)
        if parent.workspace_id != task.workspace_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Parent task is outside this workspace")
    for field, value in updates.items():
        setattr(task, field, value)
    if "status" in updates:
        set_task_completion_fields(task)
    task.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(task)
    return serialize_task(task)


@router.delete("/api/tasks/{task_id}", response_model=DeleteResponse)
def delete_task(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DeleteResponse:
    task, member = get_task_for_user(db, user, task_id, WRITE_ROLES)
    require_workspace_role(member, WRITE_ROLES)
    db.delete(task)
    db.commit()
    return DeleteResponse()
