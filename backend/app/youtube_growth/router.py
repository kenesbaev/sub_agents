from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.connected_apps.router import refresh_due_oauth_tokens
from app.core_domain.service import READ_ROLES, WRITE_ROLES, ensure_workspace_member, get_workspace_context, require_workspace_role
from app.db.session import get_db
from app.models import User, YouTubeAnalysisRun, YouTubeContentPlan
from app.security import get_current_user
from app.youtube_growth.errors import YouTubeGrowthError, YouTubeNotFoundError
from app.youtube_growth.schemas import (
    AnalysisResponse,
    ChannelAnalysisRequest,
    CompetitorAnalysisRequest,
    ContentPlanCreateRequest,
    ContentPlanItemPatchRequest,
    ContentPlanItemResponse,
    ContentPlanResponse,
    DelegateRequest,
    DelegateResponse,
    GrowthSnapshotCreateRequest,
    GrowthSnapshotResponse,
    VideoAnalysisRequest,
    YouTubeOverviewResponse,
)
from app.youtube_growth.service import (
    analysis_response,
    analyze_channel,
    analyze_competitors,
    analyze_video,
    create_content_plan,
    create_growth_snapshot,
    delegate_to_youtube_team,
    overview,
    plan_response,
    recommendations,
    update_content_plan_item,
)


router = APIRouter(prefix="/api/youtube-growth", tags=["youtube-growth"])


def _raise_domain_error(exc: YouTubeGrowthError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message, "retryable": exc.retryable},
    ) from exc


def _workspace_id(db: Session, user: User, requested_workspace_id: int | None, *, write: bool) -> int:
    context = get_workspace_context(db, user, requested_workspace_id)
    require_workspace_role(context.member, WRITE_ROLES if write else READ_ROLES)
    return context.workspace.id


@router.get("/overview", response_model=YouTubeOverviewResponse)
@router.get("/status", response_model=YouTubeOverviewResponse, include_in_schema=False)
async def get_overview(
    workspace_id: int | None = Query(default=None, ge=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> YouTubeOverviewResponse:
    await refresh_due_oauth_tokens(db, user)
    resolved_workspace_id = _workspace_id(db, user, workspace_id, write=False)
    response = overview(db, settings, user, resolved_workspace_id)
    db.commit()
    return response


@router.post("/analyze/video", response_model=AnalysisResponse, status_code=status.HTTP_201_CREATED)
async def post_video_analysis(
    payload: VideoAnalysisRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AnalysisResponse:
    await refresh_due_oauth_tokens(db, user)
    workspace_id = _workspace_id(db, user, payload.workspace_id, write=True)
    try:
        return await analyze_video(db, settings, user, workspace_id, payload)
    except YouTubeGrowthError as exc:
        _raise_domain_error(exc)


@router.post("/analyze/channel", response_model=AnalysisResponse, status_code=status.HTTP_201_CREATED)
async def post_channel_analysis(
    payload: ChannelAnalysisRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AnalysisResponse:
    await refresh_due_oauth_tokens(db, user)
    workspace_id = _workspace_id(db, user, payload.workspace_id, write=True)
    try:
        return await analyze_channel(db, settings, user, workspace_id, payload)
    except YouTubeGrowthError as exc:
        _raise_domain_error(exc)


@router.post("/analyze/competitors", response_model=AnalysisResponse, status_code=status.HTTP_201_CREATED)
async def post_competitor_analysis(
    payload: CompetitorAnalysisRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AnalysisResponse:
    await refresh_due_oauth_tokens(db, user)
    workspace_id = _workspace_id(db, user, payload.workspace_id, write=True)
    try:
        return await analyze_competitors(db, settings, user, workspace_id, payload)
    except YouTubeGrowthError as exc:
        _raise_domain_error(exc)


@router.get("/analyses/{analysis_id}", response_model=AnalysisResponse)
def get_analysis(
    analysis_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnalysisResponse:
    analysis = db.get(YouTubeAnalysisRun, analysis_id)
    if analysis is None:
        _raise_domain_error(YouTubeNotFoundError("YouTube analysis was not found."))
    ensure_workspace_member(db, user, analysis.workspace_id, READ_ROLES)
    return analysis_response(db, analysis)


@router.post("/content-plans", response_model=ContentPlanResponse, status_code=status.HTTP_201_CREATED)
async def post_content_plan(
    payload: ContentPlanCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ContentPlanResponse:
    await refresh_due_oauth_tokens(db, user)
    workspace_id = _workspace_id(db, user, payload.workspace_id, write=True)
    try:
        return await create_content_plan(db, settings, user, workspace_id, payload)
    except YouTubeGrowthError as exc:
        _raise_domain_error(exc)


@router.get("/content-plans/{plan_id}", response_model=ContentPlanResponse)
def get_content_plan(
    plan_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ContentPlanResponse:
    plan = db.get(YouTubeContentPlan, plan_id)
    if plan is None:
        _raise_domain_error(YouTubeNotFoundError("YouTube content plan was not found."))
    ensure_workspace_member(db, user, plan.workspace_id, READ_ROLES)
    return plan_response(db, plan)


@router.patch(
    "/content-plans/{plan_id}/items/{item_id}",
    response_model=ContentPlanItemResponse,
)
def patch_content_plan_item(
    plan_id: int,
    item_id: int,
    payload: ContentPlanItemPatchRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ContentPlanItemResponse:
    try:
        return update_content_plan_item(db, user, plan_id, item_id, payload)
    except YouTubeGrowthError as exc:
        _raise_domain_error(exc)


@router.post("/growth-snapshots", response_model=GrowthSnapshotResponse, status_code=status.HTTP_201_CREATED)
async def post_growth_snapshot(
    payload: GrowthSnapshotCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> GrowthSnapshotResponse:
    await refresh_due_oauth_tokens(db, user)
    workspace_id = _workspace_id(db, user, payload.workspace_id, write=True)
    try:
        return await create_growth_snapshot(db, settings, user, workspace_id, payload)
    except YouTubeGrowthError as exc:
        _raise_domain_error(exc)


@router.get("/recommendations", response_model=list[GrowthSnapshotResponse])
def get_recommendations(
    workspace_id: int | None = Query(default=None, ge=1),
    video_id: str | None = Query(default=None, min_length=3, max_length=64),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[GrowthSnapshotResponse]:
    resolved_workspace_id = _workspace_id(db, user, workspace_id, write=False)
    db.commit()
    return recommendations(db, resolved_workspace_id, video_id)


@router.post("/delegate", response_model=DelegateResponse, status_code=status.HTTP_201_CREATED)
def post_delegate(
    payload: DelegateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DelegateResponse:
    try:
        return delegate_to_youtube_team(db, user, payload)
    except YouTubeGrowthError as exc:
        _raise_domain_error(exc)
