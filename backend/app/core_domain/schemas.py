from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

WorkspaceRole = Literal["owner", "admin", "member", "viewer"]
AgentStatus = Literal["ready", "planning", "working", "waiting", "completed", "failed", "offline"]
TeamStatus = Literal["ready", "active", "paused", "archived"]
TaskStatus = Literal[
    "queued",
    "planning",
    "assigned",
    "in_progress",
    "waiting",
    "waiting_for_approval",
    "completed",
    "failed",
    "cancelled",
]
TaskPriority = Literal["low", "normal", "high", "urgent"]


class WorkspaceResponse(BaseModel):
    id: int
    name: str
    slug: str
    owner_id: int
    created_at: datetime
    updated_at: datetime


class WorkspaceMemberResponse(BaseModel):
    id: int
    workspace_id: int
    user_id: int
    role: WorkspaceRole
    created_at: datetime
    updated_at: datetime


class AgentResponse(BaseModel):
    id: int
    workspace_id: int | None
    slug: str
    name: str
    role: str
    description: str | None
    system_prompt: str | None
    provider: str | None
    model: str | None
    avatar: str | None
    status: AgentStatus
    is_system: bool
    created_at: datetime
    updated_at: datetime


class TeamAgentResponse(BaseModel):
    id: int
    team_id: int
    agent_id: int
    position: int
    role_override: str | None
    agent: AgentResponse | None = None
    created_at: datetime


class TeamResponse(BaseModel):
    id: int
    workspace_id: int
    slug: str
    name: str
    description: str | None
    category: str | None
    coordinator_agent_id: int | None
    status: TeamStatus | str
    created_by: int | None
    metadata_json: dict[str, Any] | None
    agents: list[TeamAgentResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TeamCreateRequest(BaseModel):
    workspace_id: int | None = None
    name: str = Field(min_length=1, max_length=160)
    slug: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=5000)
    category: str | None = Field(default=None, max_length=120)
    coordinator_agent_id: int | None = None
    status: TeamStatus = "ready"
    metadata_json: dict[str, Any] | None = None


class TeamUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=5000)
    category: str | None = Field(default=None, max_length=120)
    coordinator_agent_id: int | None = None
    status: TeamStatus | None = None
    metadata_json: dict[str, Any] | None = None


class TeamAgentCreateRequest(BaseModel):
    agent_id: int
    position: int = Field(default=0, ge=0, le=999)
    role_override: str | None = Field(default=None, max_length=160)


class TaskResponse(BaseModel):
    id: int
    workspace_id: int
    team_id: int | None
    assigned_agent_id: int | None
    parent_task_id: int | None
    title: str
    description: str | None
    status: TaskStatus | str
    priority: TaskPriority | str
    progress: int
    input_json: dict[str, Any] | None
    result_json: dict[str, Any] | None
    error: str | None
    created_by: int | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime


class TaskCreateRequest(BaseModel):
    workspace_id: int | None = None
    team_id: int | None = None
    assigned_agent_id: int | None = None
    parent_task_id: int | None = None
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    status: TaskStatus = "queued"
    priority: TaskPriority = "normal"
    progress: int = Field(default=0, ge=0, le=100)
    input_json: dict[str, Any] | None = None


class TaskUpdateRequest(BaseModel):
    team_id: int | None = None
    assigned_agent_id: int | None = None
    parent_task_id: int | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    input_json: dict[str, Any] | None = None
    result_json: dict[str, Any] | None = None
    error: str | None = Field(default=None, max_length=10000)

    @field_validator("result_json", "input_json")
    @classmethod
    def keep_json_objects(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return value


class DeleteResponse(BaseModel):
    ok: bool = True

