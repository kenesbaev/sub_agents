from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core_domain.schemas import WorkspaceRole


PlanCode = Literal["start", "plus", "pro", "custom"]


class PlanSummary(BaseModel):
    code: PlanCode
    name: str


class BillingStatusResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    workspace_id: int = Field(serialization_alias="workspaceId")
    role: WorkspaceRole
    plan: PlanSummary | None
    can_upgrade: bool = Field(serialization_alias="canUpgrade")
