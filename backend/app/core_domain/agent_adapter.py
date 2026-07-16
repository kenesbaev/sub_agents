from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent


@dataclass(frozen=True)
class RuntimeAgentProfile:
    id: str
    name: str
    role: str
    system_prompt: str
    provider: str | None = None
    model: str | None = None
    avatar: str | None = None


def agent_to_runtime_profile(agent: Agent) -> RuntimeAgentProfile:
    return RuntimeAgentProfile(
        id=agent.slug,
        name=agent.name,
        role=agent.role,
        system_prompt=agent.system_prompt or agent.description or "",
        provider=agent.provider,
        model=agent.model,
        avatar=agent.avatar,
    )


def list_workspace_runtime_agents(db: Session, workspace_id: int) -> list[RuntimeAgentProfile]:
    agents = db.scalars(
        select(Agent)
        .where((Agent.workspace_id == workspace_id) | (Agent.workspace_id.is_(None)))
        .order_by(Agent.is_system.desc(), Agent.name)
    ).all()
    return [agent_to_runtime_profile(agent) for agent in agents]

