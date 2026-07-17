from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


GROWTH_SCORE_DISCLAIMER = "This score estimates content potential and does not guarantee a specific number of views."

AnalysisKind = Literal["video", "channel", "competitors"]
AnalysisStatus = Literal["queued", "running", "completed", "partial", "failed"]
ContentFormat = Literal["long_video", "short", "live"]
ContentGoal = Literal["awareness", "engagement", "leads", "sales"]
Confidence = Literal["low", "medium", "high"]
GrowthCheckpoint = Literal["1h", "6h", "24h", "72h", "7d"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SourceReference(StrictModel):
    url: str = Field(min_length=8, max_length=2048)
    source_type: str = Field(min_length=1, max_length=80)
    title: str | None = Field(default=None, max_length=500)
    external_id: str | None = Field(default=None, max_length=255)
    published_at: datetime | None = None
    timestamp_seconds: int | None = Field(default=None, ge=0)
    fact: str | None = Field(default=None, max_length=2000)


class ScoreComponent(StrictModel):
    score: int = Field(ge=0, le=100)
    explanation: str = Field(min_length=1, max_length=1000)


class GrowthScoreComponents(StrictModel):
    topic_demand: ScoreComponent
    competition_gap: ScoreComponent
    hook_strength: ScoreComponent
    title_thumbnail_packaging: ScoreComponent
    channel_fit: ScoreComponent
    timing_relevance: ScoreComponent


class GrowthScoreBreakdown(StrictModel):
    topic: str = Field(min_length=1, max_length=500)
    components: GrowthScoreComponents
    total_score: int = Field(ge=0, le=100)
    explanation: str = Field(min_length=1, max_length=2000)


class ContentPlanItem(StrictModel):
    """The public, validated Teamora content-plan artifact schema."""

    publish_date: date
    content_pillar: str = Field(min_length=1, max_length=200)
    target_audience: str = Field(min_length=1, max_length=500)
    topic: str = Field(min_length=1, max_length=500)
    why_now: str = Field(min_length=1, max_length=1500)
    format: ContentFormat
    goal: ContentGoal
    estimated_duration: str = Field(min_length=1, max_length=100)
    titles: list[str] = Field(min_length=3, max_length=3)
    hooks: list[str] = Field(min_length=3, max_length=3)
    thumbnail_briefs: list[str] = Field(min_length=2, max_length=2)
    script_outline: list[str] = Field(min_length=1, max_length=30)
    cta: str = Field(min_length=1, max_length=1000)
    description_draft: str = Field(min_length=1, max_length=5000)
    chapters: list[str] = Field(default_factory=list, max_length=50)
    shorts_ideas: list[str] = Field(default_factory=list, max_length=20)
    facts_to_verify: list[str] = Field(default_factory=list, max_length=30)
    sources: list[str] = Field(default_factory=list, max_length=50)
    primary_kpi: str = Field(min_length=1, max_length=200)
    opportunity_score: int = Field(ge=0, le=100)
    confidence: Confidence
    score_explanation: str = Field(min_length=1, max_length=2000)

    @field_validator(
        "titles", "hooks", "thumbnail_briefs", "script_outline", "chapters", "shorts_ideas", "facts_to_verify", "sources"
    )
    @classmethod
    def clean_string_lists(cls, value: list[str]) -> list[str]:
        result = [str(item).strip() for item in value]
        if any(not item for item in result):
            raise ValueError("list items must be non-empty strings")
        return result


class ContentPlanItemPatchRequest(StrictModel):
    """User-controlled edits for one persisted plan item.

    Opportunity score fields are deliberately absent: callers may either leave
    the persisted score untouched or submit a complete, validated component set
    for a server-side recalculation.
    """

    publish_date: date | None = None
    content_pillar: str | None = Field(default=None, min_length=1, max_length=200)
    target_audience: str | None = Field(default=None, min_length=1, max_length=500)
    topic: str | None = Field(default=None, min_length=1, max_length=500)
    why_now: str | None = Field(default=None, min_length=1, max_length=1500)
    format: ContentFormat | None = None
    goal: ContentGoal | None = None
    estimated_duration: str | None = Field(default=None, min_length=1, max_length=100)
    titles: list[str] | None = Field(default=None, min_length=3, max_length=3)
    hooks: list[str] | None = Field(default=None, min_length=3, max_length=3)
    thumbnail_briefs: list[str] | None = Field(default=None, min_length=2, max_length=2)
    script_outline: list[str] | None = Field(default=None, min_length=1, max_length=30)
    cta: str | None = Field(default=None, min_length=1, max_length=1000)
    description_draft: str | None = Field(default=None, min_length=1, max_length=5000)
    chapters: list[str] | None = Field(default=None, max_length=50)
    shorts_ideas: list[str] | None = Field(default=None, max_length=20)
    facts_to_verify: list[str] | None = Field(default=None, max_length=30)
    sources: list[str] | None = Field(default=None, max_length=50)
    primary_kpi: str | None = Field(default=None, min_length=1, max_length=200)
    confidence: Confidence | None = None
    approved: bool | None = None
    score_components: GrowthScoreComponents | None = None

    @field_validator(
        "titles", "hooks", "thumbnail_briefs", "script_outline", "chapters", "shorts_ideas", "facts_to_verify", "sources"
    )
    @classmethod
    def clean_optional_string_lists(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        result = [str(item).strip() for item in value]
        if any(not item for item in result):
            raise ValueError("list items must be non-empty strings")
        return result

    @model_validator(mode="after")
    def require_non_null_change(self) -> "ContentPlanItemPatchRequest":
        if not self.model_fields_set:
            raise ValueError("at least one plan-item field must be provided")
        null_fields = [name for name in self.model_fields_set if getattr(self, name) is None]
        if null_fields:
            raise ValueError(f"plan-item fields cannot be null: {', '.join(sorted(null_fields))}")
        return self


class GeneratedPlanEntry(StrictModel):
    item: ContentPlanItem
    score_components: GrowthScoreComponents


class GeneratedContentPlan(StrictModel):
    items: list[GeneratedPlanEntry] = Field(min_length=1, max_length=30)


class WorkspaceRequest(StrictModel):
    workspace_id: int | None = Field(default=None, ge=1)
    account_id: int | None = Field(default=None, ge=1)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)


class VideoAnalysisRequest(WorkspaceRequest):
    url: str = Field(min_length=3, max_length=2048)
    language: str | None = Field(default=None, max_length=16)
    region: str | None = Field(default=None, min_length=2, max_length=2)
    include_comments: bool = True
    include_captions: bool = True
    comment_limit: int = Field(default=50, ge=1, le=100)


class ChannelAnalysisRequest(WorkspaceRequest):
    url: str = Field(min_length=2, max_length=2048)
    language: str | None = Field(default=None, max_length=16)
    region: str | None = Field(default=None, min_length=2, max_length=2)
    max_videos: int = Field(default=25, ge=1, le=50)


class CompetitorAnalysisRequest(WorkspaceRequest):
    query: str = Field(min_length=2, max_length=500)
    language: str | None = Field(default=None, max_length=16)
    region: str | None = Field(default=None, min_length=2, max_length=2)
    limit: int = Field(default=20, ge=10, le=50)


class ContentPlanCreateRequest(WorkspaceRequest):
    analysis_ids: list[int] = Field(default_factory=list, max_length=20)
    days: Literal[7, 30] = 7
    niche: str = Field(min_length=2, max_length=300)
    language: str = Field(min_length=2, max_length=32)
    region: str = Field(min_length=2, max_length=100)
    goal: ContentGoal
    publishing_frequency: str = Field(min_length=1, max_length=200)
    content_pillars: list[str] = Field(min_length=1, max_length=12)
    target_audience: str | None = Field(default=None, max_length=1000)

    @field_validator("content_pillars")
    @classmethod
    def clean_pillars(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("content pillars must be non-empty")
        return cleaned


class GrowthSnapshotCreateRequest(WorkspaceRequest):
    account_id: int = Field(ge=1)
    video_id: str = Field(min_length=3, max_length=64)
    checkpoint: GrowthCheckpoint
    baseline_video_count: int = Field(default=20, ge=5, le=50)


class AnalysisResponse(StrictModel):
    id: int
    kind: AnalysisKind
    status: AnalysisStatus
    summary: str
    facts: dict[str, Any]
    insights: dict[str, Any]
    limitations: list[str]
    metrics: dict[str, Any]
    sources: list[SourceReference]
    partial: bool
    opportunity_score: int | None = Field(default=None, ge=0, le=100)
    score_components: GrowthScoreBreakdown | None = None
    error_code: str | None = None
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class ContentPlanItemResponse(StrictModel):
    id: int
    plan_id: int
    position: int = Field(ge=0)
    approved: bool
    item: ContentPlanItem
    score_breakdown: GrowthScoreBreakdown
    updated_at: datetime


class ContentPlanResponse(StrictModel):
    id: int
    status: Literal["queued", "running", "completed", "failed"]
    days: Literal[7, 30]
    items: list[ContentPlanItem]
    item_records: list[ContentPlanItemResponse]
    score_breakdowns: list[GrowthScoreBreakdown]
    disclaimer: str = GROWTH_SCORE_DISCLAIMER
    limitations: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime

    @model_validator(mode="after")
    def validate_plan_length(self) -> "ContentPlanResponse":
        if self.status == "completed" and len(self.items) != self.days:
            raise ValueError(f"a {self.days}-day plan must contain exactly {self.days} items")
        if len(self.score_breakdowns) != len(self.items):
            raise ValueError("each plan item requires a score breakdown")
        if len(self.item_records) != len(self.items):
            raise ValueError("each plan item requires an editable item record")
        return self


class GrowthSnapshotResponse(StrictModel):
    id: int
    video_id: str
    checkpoint: GrowthCheckpoint
    status: Literal["queued", "running", "completed", "partial", "failed"]
    metrics: dict[str, Any]
    baseline: dict[str, Any]
    recommendations: list[str]
    limitations: list[str]
    sources: list[SourceReference]
    error_code: str | None = None
    error: str | None = None
    scheduled_for: datetime | None
    observed_at: datetime | None
    created_at: datetime


class YouTubeAccountStatus(StrictModel):
    id: int
    channel_id: str
    label: str | None
    connected: bool
    can_read: bool
    can_analyze_private_metrics: bool
    can_upload: bool


class YouTubeOverviewResponse(StrictModel):
    workspace_id: int
    public_research_available: bool
    connected: bool
    connection_state: str
    accounts: list[YouTubeAccountStatus]
    missing_permissions: list[str]
    recent_analyses: list[AnalysisResponse]
    recent_plans: list[ContentPlanResponse]
    disclaimer: str = GROWTH_SCORE_DISCLAIMER


class DelegateRequest(StrictModel):
    workspace_id: int | None = Field(default=None, ge=1)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)
    action: Literal["analyze_video", "analyze_channel", "analyze_competitors", "create_content_plan", "growth_snapshot"]
    input: dict[str, Any] = Field(default_factory=dict)
    artifact_ids: list[int] = Field(default_factory=list, max_length=50)


class DelegatedTask(StrictModel):
    id: int
    role: str
    status: str


class DelegateResponse(StrictModel):
    coordinator_task_id: int
    child_tasks: list[DelegatedTask]
    artifact_ids: list[int]
    status: Literal["queued"] = "queued"
    message: str
