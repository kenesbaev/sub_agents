from __future__ import annotations

import logging
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.billing.schemas import BillingStatusResponse, PlanCode, PlanSummary
from app.core_domain.service import ADMIN_ROLES, get_workspace_context
from app.db.session import get_db
from app.models import User, Workspace
from app.security import get_current_user


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/billing", tags=["billing"])

PLAN_NAMES: dict[PlanCode, str] = {
    "start": "Start",
    "plus": "Plus",
    "pro": "Pro",
    "custom": "Custom",
}


def plan_summary(workspace: Workspace) -> PlanSummary | None:
    raw_code = workspace.plan_code
    if raw_code is None:
        return None

    normalized = raw_code.strip().lower()
    if normalized != raw_code or normalized not in PLAN_NAMES:
        logger.error("invalid workspace plan code (workspace_id=%s)", workspace.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Workspace plan configuration is invalid.",
        )

    code = cast(PlanCode, normalized)
    return PlanSummary(code=code, name=PLAN_NAMES[code])


@router.get("/status", response_model=BillingStatusResponse)
def billing_status(
    workspace_id: int | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BillingStatusResponse:
    context = get_workspace_context(db, user, workspace_id)
    plan = plan_summary(context.workspace)
    db.commit()
    return BillingStatusResponse(
        workspace_id=context.workspace.id,
        role=context.member.role,
        plan=plan,
        can_upgrade=plan is None and context.member.role in ADMIN_ROLES,
    )
