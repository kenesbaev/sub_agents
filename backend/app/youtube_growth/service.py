from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core_domain.service import WRITE_ROLES, get_workspace_context, require_workspace_role, seed_default_workspace
from app.models import (
    Agent,
    IntegrationAccount,
    IntegrationProvider,
    IntegrationToken,
    Task,
    Team,
    TeamAgent,
    User,
    UserIntegration,
    YouTubeAnalysisRun,
    YouTubeAnalysisSource,
    YouTubeContentPlan,
    YouTubeContentPlanItem,
    YouTubeGrowthSnapshot,
)
from app.token_crypto import decrypt_token
from app.youtube_growth.client import YouTubeClient, video_id_from_reference
from app.youtube_growth.errors import (
    AnalyticsUnavailableError,
    CaptionsUnavailableError,
    CommentsDisabledError,
    IdempotencyConflictError,
    ModelUnavailableError,
    OperationInProgressError,
    YouTubeGrowthError,
    YouTubeNotConnectedError,
    YouTubeNotFoundError,
    YouTubePermissionError,
    YouTubeTeamUnavailableError,
)
from app.youtube_growth.llm import HttpJsonModelClient, JsonModelClient, generate_validated_content_plan
from app.youtube_growth.schemas import (
    AnalysisResponse,
    ChannelAnalysisRequest,
    CompetitorAnalysisRequest,
    ContentPlanCreateRequest,
    ContentPlanItem,
    ContentPlanItemPatchRequest,
    ContentPlanItemResponse,
    ContentPlanResponse,
    DelegateRequest,
    DelegateResponse,
    DelegatedTask,
    GROWTH_SCORE_DISCLAIMER,
    GrowthScoreBreakdown,
    GrowthScoreComponents,
    GrowthSnapshotCreateRequest,
    GrowthSnapshotResponse,
    ScoreComponent,
    SourceReference,
    VideoAnalysisRequest,
    YouTubeAccountStatus,
    YouTubeOverviewResponse,
)
from app.youtube_growth.scoring import calculate_growth_opportunity_score


YOUTUBE_READ_SCOPES = {
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
}
YOUTUBE_ANALYTICS_SCOPES = {
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
}
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
MAX_UNTRUSTED_COMMENT_CHARS = 20_000
MAX_TRANSCRIPT_CHARS = 60_000
MAX_TRANSCRIPT_SOURCE_REFERENCES = 20
SRT_BLOCK_RE = re.compile(
    r"(?:^|\n)(?:\d+\s*\n)?(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3}).*?\n(?P<text>.*?)(?=\n\s*\n|\Z)",
    re.DOTALL,
)


@dataclass(frozen=True)
class YouTubeCredentials:
    account_id: int
    channel_id: str
    access_token: str
    scopes: frozenset[str]
    label: str | None

    @property
    def can_read(self) -> bool:
        return bool(self.scopes.intersection(YOUTUBE_READ_SCOPES))

    @property
    def can_analyze_private_metrics(self) -> bool:
        return self.can_read and bool(self.scopes.intersection(YOUTUBE_ANALYTICS_SCOPES))

    @property
    def can_upload(self) -> bool:
        return YOUTUBE_UPLOAD_SCOPE in self.scopes


def _scope_values(value: str | None) -> frozenset[str]:
    return frozenset(part for part in (value or "").replace(",", " ").split() if part)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def load_youtube_credentials(
    db: Session,
    user: User,
    *,
    account_id: int | None = None,
    required: bool = False,
) -> YouTubeCredentials | None:
    provider = db.scalar(select(IntegrationProvider).where(IntegrationProvider.key == "youtube"))
    if provider is None:
        if account_id is not None:
            raise YouTubePermissionError("The selected YouTube account does not belong to the authenticated user.")
        if required:
            raise YouTubeNotConnectedError()
        return None
    integration = db.scalar(
        select(UserIntegration).where(
            UserIntegration.user_id == user.id,
            UserIntegration.provider_id == provider.id,
            UserIntegration.status == "connected",
        )
    )
    if integration is None:
        if account_id is not None:
            raise YouTubePermissionError("The selected YouTube account does not belong to the authenticated user.")
        if required:
            raise YouTubeNotConnectedError()
        return None
    query = select(IntegrationAccount).where(
        IntegrationAccount.user_integration_id == integration.id,
        IntegrationAccount.provider_id == provider.id,
    )
    if account_id is not None:
        query = query.where(IntegrationAccount.id == account_id)
    account = db.scalar(query.order_by(IntegrationAccount.is_default.desc(), IntegrationAccount.id))
    if account is None:
        if required or account_id is not None:
            raise YouTubePermissionError("The selected YouTube account does not belong to the authenticated user.")
        return None
    token = db.scalar(
        select(IntegrationToken).where(
            IntegrationToken.user_integration_id == integration.id,
            IntegrationToken.integration_account_id == account.id,
        )
    )
    if token is None or not token.encrypted_access_token:
        if required or account_id is not None:
            raise YouTubeNotConnectedError("YouTube authorization is incomplete. Reconnect YouTube.")
        return None
    expires_at = _as_utc(token.expires_at)
    if expires_at is not None and expires_at <= datetime.now(UTC):
        if required or account_id is not None:
            raise YouTubeNotConnectedError("YouTube authorization expired. Reconnect YouTube.")
        return None
    try:
        access_token = decrypt_token(token.encrypted_access_token)
    except Exception as exc:
        raise YouTubeNotConnectedError("YouTube authorization could not be read. Reconnect YouTube.") from exc
    return YouTubeCredentials(
        account_id=account.id,
        channel_id=account.account_identifier,
        access_token=access_token,
        scopes=_scope_values(token.scopes),
        label=account.account_label,
    )


def list_youtube_account_statuses(db: Session, user: User) -> list[YouTubeAccountStatus]:
    provider = db.scalar(select(IntegrationProvider).where(IntegrationProvider.key == "youtube"))
    if provider is None:
        return []
    integration = db.scalar(
        select(UserIntegration).where(UserIntegration.user_id == user.id, UserIntegration.provider_id == provider.id)
    )
    if integration is None:
        return []
    accounts = db.scalars(
        select(IntegrationAccount)
        .where(IntegrationAccount.user_integration_id == integration.id, IntegrationAccount.provider_id == provider.id)
        .order_by(IntegrationAccount.is_default.desc(), IntegrationAccount.id)
    ).all()
    statuses: list[YouTubeAccountStatus] = []
    for account in accounts:
        token = db.scalar(select(IntegrationToken).where(IntegrationToken.integration_account_id == account.id))
        scopes = _scope_values(token.scopes if token else None)
        connected = bool(
            integration.status == "connected"
            and token
            and token.encrypted_access_token
            and (_as_utc(token.expires_at) is None or _as_utc(token.expires_at) > datetime.now(UTC))
        )
        statuses.append(
            YouTubeAccountStatus(
                id=account.id,
                channel_id=account.account_identifier,
                label=account.account_label,
                connected=connected,
                can_read=connected and bool(scopes.intersection(YOUTUBE_READ_SCOPES)),
                can_analyze_private_metrics=(
                    connected
                    and bool(scopes.intersection(YOUTUBE_READ_SCOPES))
                    and bool(scopes.intersection(YOUTUBE_ANALYTICS_SCOPES))
                ),
                can_upload=connected and YOUTUBE_UPLOAD_SCOPE in scopes,
            )
        )
    return statuses


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _video_metrics(video: dict[str, Any]) -> dict[str, Any]:
    statistics_data = video.get("statistics") if isinstance(video.get("statistics"), dict) else {}
    return {
        "views": _optional_int(statistics_data.get("viewCount")),
        "likes": _optional_int(statistics_data.get("likeCount")),
        "comments": _optional_int(statistics_data.get("commentCount")),
        "favorites": _optional_int(statistics_data.get("favoriteCount")),
    }


def _video_facts(video: dict[str, Any]) -> dict[str, Any]:
    snippet = video.get("snippet") if isinstance(video.get("snippet"), dict) else {}
    content = video.get("contentDetails") if isinstance(video.get("contentDetails"), dict) else {}
    status_data = video.get("status") if isinstance(video.get("status"), dict) else {}
    return {
        "video_id": str(video.get("id") or ""),
        "channel_id": str(snippet.get("channelId") or ""),
        "channel_title": str(snippet.get("channelTitle") or "")[:500],
        "title": str(snippet.get("title") or "")[:500],
        "description": str(snippet.get("description") or "")[:10_000],
        "published_at": snippet.get("publishedAt"),
        "tags": [str(tag)[:200] for tag in snippet.get("tags", [])[:50]] if isinstance(snippet.get("tags"), list) else [],
        "category_id": snippet.get("categoryId"),
        "duration": content.get("duration"),
        "definition": content.get("definition"),
        "caption_available": content.get("caption") == "true",
        "privacy_status": status_data.get("privacyStatus"),
        "made_for_kids": status_data.get("madeForKids"),
    }


def _channel_facts(channel: dict[str, Any]) -> dict[str, Any]:
    snippet = channel.get("snippet") if isinstance(channel.get("snippet"), dict) else {}
    statistics_data = channel.get("statistics") if isinstance(channel.get("statistics"), dict) else {}
    hidden = bool(statistics_data.get("hiddenSubscriberCount"))
    return {
        "channel_id": str(channel.get("id") or ""),
        "title": str(snippet.get("title") or "")[:500],
        "description": str(snippet.get("description") or "")[:10_000],
        "published_at": snippet.get("publishedAt"),
        "country": snippet.get("country"),
        "subscriber_count": None if hidden else _optional_int(statistics_data.get("subscriberCount")),
        "hidden_subscriber_count": hidden,
        "view_count": _optional_int(statistics_data.get("viewCount")),
        "video_count": _optional_int(statistics_data.get("videoCount")),
    }


def _comment_facts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    remaining = MAX_UNTRUSTED_COMMENT_CHARS
    for item in items:
        snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
        top = snippet.get("topLevelComment") if isinstance(snippet.get("topLevelComment"), dict) else {}
        comment = top.get("snippet") if isinstance(top.get("snippet"), dict) else {}
        text = str(comment.get("textDisplay") or comment.get("textOriginal") or "")
        text = text[: min(2000, remaining)]
        if not text:
            continue
        remaining -= len(text)
        result.append(
            {
                "text": text,
                "like_count": _optional_int(comment.get("likeCount")),
                "published_at": comment.get("publishedAt"),
                "reply_count": _optional_int(snippet.get("totalReplyCount")),
                "trust": "untrusted_external_data",
            }
        )
        if remaining <= 0:
            break
    return result


def _comment_signals(comments: list[dict[str, Any]]) -> dict[str, Any]:
    positive_terms = ("helpful", "great", "love", "thanks", "useful", "полез", "спасибо", "отлич")
    negative_terms = ("wrong", "bad", "confusing", "hate", "doesn't work", "ошиб", "плохо", "не работает")
    recurring: Counter[str] = Counter()
    positive_count = 0
    negative_count = 0
    question_count = 0
    for comment in comments:
        text = str(comment.get("text") or "").casefold()
        if any(term in text for term in positive_terms):
            positive_count += 1
        if any(term in text for term in negative_terms):
            negative_count += 1
        if "?" in text:
            question_count += 1
        recurring.update(
            {
                token
                for token in TITLE_TOKEN_RE.findall(text)
                if token not in TITLE_STOPWORDS and not token.isdigit()
            }
        )
    return {
        "positive_lexical_matches": positive_count,
        "negative_lexical_matches": negative_count,
        "questions": question_count,
        "repeated_terms": [
            {"term": term, "comment_count": count}
            for term, count in recurring.most_common(10)
            if count >= 2
        ],
        "method_limit": (
            "Surface keyword and recurring-term signals from untrusted comments; this is not a definitive sentiment model."
        ),
    }


def _srt_seconds(value: str) -> int:
    hours, minutes, seconds = value.replace(",", ".").split(":")
    return round(int(hours) * 3600 + int(minutes) * 60 + float(seconds))


def parse_srt(text: str) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    remaining = MAX_TRANSCRIPT_CHARS
    for match in SRT_BLOCK_RE.finditer(text[: MAX_TRANSCRIPT_CHARS * 2]):
        clean = " ".join(re.sub(r"<[^>]+>", " ", match.group("text")).split())
        if not clean:
            continue
        clean = clean[:remaining]
        segments.append(
            {
                "start_seconds": _srt_seconds(match.group("start")),
                "end_seconds": _srt_seconds(match.group("end")),
                "text": clean,
                "trust": "untrusted_external_data",
            }
        )
        remaining -= len(clean)
        if remaining <= 0:
            break
    return segments


def _transcript_sources(
    video_id: str,
    video_title: str,
    transcript: list[dict[str, Any]],
) -> list[SourceReference]:
    """Expose bounded, evenly distributed caption evidence with deep links."""

    if not transcript:
        return []
    if len(transcript) <= MAX_TRANSCRIPT_SOURCE_REFERENCES:
        indices = list(range(len(transcript)))
    else:
        last = len(transcript) - 1
        indices = sorted(
            {
                round(index * last / (MAX_TRANSCRIPT_SOURCE_REFERENCES - 1))
                for index in range(MAX_TRANSCRIPT_SOURCE_REFERENCES)
            }
        )

    sources: list[SourceReference] = []
    for index in indices:
        segment = transcript[index]
        timestamp = max(0, int(segment.get("start_seconds") or 0))
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        sources.append(
            SourceReference(
                url=f"https://www.youtube.com/watch?v={video_id}&t={timestamp}s",
                source_type="authorized_youtube_caption",
                external_id=video_id,
                title=f"{video_title} — caption at {timestamp}s",
                timestamp_seconds=timestamp,
                fact=f"Authorized caption segment: {text[:500]}",
            )
        )
    return sources


def _begin_analysis(
    db: Session,
    user: User,
    workspace_id: int,
    *,
    kind: str,
    target_url: str,
    target_id: str | None,
    account_id: int | None,
    request_json: dict[str, Any],
    idempotency_key: str | None,
) -> YouTubeAnalysisRun:
    if idempotency_key:
        existing = db.scalar(
            select(YouTubeAnalysisRun).where(
                YouTubeAnalysisRun.workspace_id == workspace_id,
                YouTubeAnalysisRun.idempotency_key == idempotency_key,
            )
        )
        if existing:
            if existing.status in {"queued", "running"}:
                raise OperationInProgressError("This YouTube analysis is already in progress.")
            return existing
    analysis = YouTubeAnalysisRun(
        workspace_id=workspace_id,
        created_by=user.id,
        integration_account_id=account_id,
        kind=kind,
        target_id=target_id,
        target_url=target_url,
        status="running",
        request_json=request_json,
        idempotency_key=idempotency_key,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def _store_sources(db: Session, analysis: YouTubeAnalysisRun, sources: list[SourceReference]) -> None:
    for source in sources:
        db.add(
            YouTubeAnalysisSource(
                workspace_id=analysis.workspace_id,
                analysis_id=analysis.id,
                source_type=source.source_type,
                external_id=source.external_id,
                url=source.url,
                title=source.title,
                published_at=source.published_at,
                timestamp_seconds=source.timestamp_seconds,
                fact=source.fact,
                facts_json=source.model_dump(mode="json"),
            )
        )


def _finish_analysis(
    db: Session,
    analysis: YouTubeAnalysisRun,
    *,
    summary: str,
    facts: dict[str, Any],
    insights: dict[str, Any],
    metrics: dict[str, Any],
    limitations: list[str],
    sources: list[SourceReference],
    score: GrowthScoreBreakdown | None = None,
) -> AnalysisResponse:
    partial = bool(limitations)
    result: dict[str, Any] = {
        "summary": summary,
        "facts": facts,
        "insights": insights,
        "metrics": metrics,
        "opportunity_score": score.total_score if score else None,
        "score_components": score.model_dump(mode="json") if score else None,
    }
    analysis.result_json = result
    analysis.limitations_json = limitations
    analysis.partial = partial
    analysis.status = "partial" if partial else "completed"
    analysis.completed_at = datetime.now(UTC)
    _store_sources(db, analysis, sources)
    db.commit()
    db.refresh(analysis)
    return analysis_response(db, analysis)


def _fail_analysis(db: Session, analysis: YouTubeAnalysisRun, error: YouTubeGrowthError) -> None:
    analysis.status = "failed"
    analysis.error_code = error.code
    analysis.error = error.message
    analysis.completed_at = datetime.now(UTC)
    db.commit()


def analysis_response(db: Session, analysis: YouTubeAnalysisRun) -> AnalysisResponse:
    result = analysis.result_json or {}
    sources = db.scalars(
        select(YouTubeAnalysisSource)
        .where(YouTubeAnalysisSource.analysis_id == analysis.id, YouTubeAnalysisSource.workspace_id == analysis.workspace_id)
        .order_by(YouTubeAnalysisSource.id)
    ).all()
    return AnalysisResponse(
        id=analysis.id,
        kind=analysis.kind,
        status=analysis.status,
        summary=str(result.get("summary") or analysis.error or "Analysis is queued."),
        facts=result.get("facts") if isinstance(result.get("facts"), dict) else {},
        insights=result.get("insights") if isinstance(result.get("insights"), dict) else {},
        limitations=[str(item) for item in (analysis.limitations_json or [])],
        metrics=result.get("metrics") if isinstance(result.get("metrics"), dict) else {},
        sources=[
            SourceReference(
                url=source.url,
                source_type=source.source_type,
                title=source.title,
                external_id=source.external_id,
                published_at=source.published_at,
                timestamp_seconds=source.timestamp_seconds,
                fact=source.fact,
            )
            for source in sources
        ],
        partial=analysis.partial,
        opportunity_score=result.get("opportunity_score"),
        score_components=result.get("score_components"),
        error_code=analysis.error_code,
        error=analysis.error,
        created_at=analysis.created_at,
        completed_at=analysis.completed_at,
    )


async def analyze_video(
    db: Session,
    settings: Settings,
    user: User,
    workspace_id: int,
    request: VideoAnalysisRequest,
) -> AnalysisResponse:
    video_id = video_id_from_reference(request.url)
    credentials = load_youtube_credentials(db, user, account_id=request.account_id, required=False)
    if request.account_id is not None and credentials is not None and not credentials.can_read:
        raise YouTubePermissionError(
            "Reconnect YouTube and grant YouTube readonly permission to analyze the selected account."
        )
    analysis = _begin_analysis(
        db,
        user,
        workspace_id,
        kind="video",
        target_url=request.url,
        target_id=video_id,
        account_id=credentials.account_id if credentials else None,
        request_json=request.model_dump(mode="json"),
        idempotency_key=request.idempotency_key,
    )
    if analysis.status != "running":
        return analysis_response(db, analysis)
    client = YouTubeClient(
        db,
        settings,
        workspace_id=workspace_id,
        integration_account_id=credentials.account_id if credentials else None,
        access_token=credentials.access_token if credentials else None,
    )
    try:
        video = await client.get_video(video_id, require_oauth=request.account_id is not None)
        facts = _video_facts(video)
        metrics = _video_metrics(video)
        limitations: list[str] = []
        comments: list[dict[str, Any]] = []
        if request.include_comments:
            try:
                comments = _comment_facts(await client.comments(video_id, request.comment_limit))
            except CommentsDisabledError:
                limitations.append("Comments are disabled or unavailable; comment sentiment and audience questions were not analyzed.")
            except YouTubeGrowthError as exc:
                limitations.append(f"Comments were not analyzed: {exc.message}")
        facts["comments"] = comments

        transcript: list[dict[str, Any]] = []
        if request.include_captions:
            is_owned = bool(credentials and credentials.channel_id == facts.get("channel_id"))
            if not is_owned:
                limitations.append(
                    "Transcript unavailable through the official API for this target. The system analyzed metadata only and did not download the video."
                )
            elif not facts.get("caption_available"):
                limitations.append("YouTube reports no captions for this owned video.")
            else:
                try:
                    caption_tracks = await client.captions(video_id)
                    if not caption_tracks:
                        raise CaptionsUnavailableError()
                    preferred = next(
                        (
                            item
                            for item in caption_tracks
                            if isinstance(item.get("snippet"), dict)
                            and request.language
                            and str(item["snippet"].get("language") or "").lower().startswith(request.language.lower())
                        ),
                        caption_tracks[0],
                    )
                    caption_id = str(preferred.get("id") or "")
                    if not caption_id:
                        raise CaptionsUnavailableError()
                    transcript = parse_srt(await client.download_caption(caption_id))
                    if not transcript:
                        limitations.append("Caption track exists, but no timestamped text could be parsed.")
                except YouTubeGrowthError as exc:
                    limitations.append(f"Captions were not analyzed: {exc.message}")
        facts["transcript"] = transcript
        facts["analysis_basis"] = "metadata_comments_and_authorized_captions" if transcript else "metadata_and_available_comments"

        questions = [comment["text"] for comment in comments if "?" in comment["text"]][:20]
        insights = {
            "audience_questions": questions,
            "comment_signals": _comment_signals(comments),
            "hook": transcript[0]["text"][:500] if transcript else None,
            "structure": "Timestamped caption segments are available." if transcript else "Script structure cannot be verified without authorized captions.",
            "cta": "Not inferred from metadata alone." if not transcript else "Review the final caption segments for the spoken CTA.",
            "fact_interpretation_boundary": "Metrics and metadata are API facts; hook/structure notes are limited interpretations.",
        }
        source = SourceReference(
            url=f"https://www.youtube.com/watch?v={video_id}",
            source_type="youtube_video",
            external_id=video_id,
            title=str(facts.get("title") or "YouTube video"),
            published_at=_parse_datetime(facts.get("published_at")),
            fact="YouTube Data API metadata and statistics.",
        )
        sources = [source, *_transcript_sources(video_id, str(facts.get("title") or video_id), transcript)]
        return _finish_analysis(
            db,
            analysis,
            summary=f"Analyzed YouTube video '{facts.get('title') or video_id}' using official API data.",
            facts=facts,
            insights=insights,
            metrics=metrics,
            limitations=limitations,
            sources=sources,
        )
    except YouTubeGrowthError as exc:
        _fail_analysis(db, analysis, exc)
        raise


def _sample_metrics(videos: list[dict[str, Any]], channels: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for video in videos:
        facts = _video_facts(video)
        metrics = _video_metrics(video)
        channel = channels.get(str(facts.get("channel_id"))) if channels else None
        channel_data = _channel_facts(channel) if channel else {}
        subscribers = channel_data.get("subscriber_count")
        views = metrics.get("views")
        ratio = (
            round(views / subscribers, 4)
            if isinstance(views, int) and isinstance(subscribers, int) and subscribers > 0
            else None
        )
        rows.append({**facts, **metrics, "views_to_subscribers_ratio": ratio})
    views = [row["views"] for row in rows if isinstance(row.get("views"), int)]
    median_views = statistics.median(views) if views else 0
    breakout = [
        row for row in rows if isinstance(row.get("views"), int) and row["views"] > median_views * 2
    ] if median_views else []
    return {
        "sample_size": len(rows),
        "median_views": round(median_views, 2),
        "average_views": round(statistics.fmean(views), 2) if views else 0,
        "breakout_threshold": round(median_views * 2, 2),
        "breakout_videos": breakout,
        "videos": rows,
    }


async def analyze_channel(
    db: Session,
    settings: Settings,
    user: User,
    workspace_id: int,
    request: ChannelAnalysisRequest,
) -> AnalysisResponse:
    credentials = load_youtube_credentials(db, user, account_id=request.account_id, required=False)
    analysis = _begin_analysis(
        db,
        user,
        workspace_id,
        kind="channel",
        target_url=request.url,
        target_id=None,
        account_id=credentials.account_id if credentials else None,
        request_json=request.model_dump(mode="json"),
        idempotency_key=request.idempotency_key,
    )
    if analysis.status != "running":
        return analysis_response(db, analysis)
    client = YouTubeClient(
        db,
        settings,
        workspace_id=workspace_id,
        integration_account_id=credentials.account_id if credentials else None,
        access_token=credentials.access_token if credentials else None,
    )
    try:
        channel = await client.resolve_channel(request.url)
        videos = await client.channel_videos(channel, request.max_videos)
        channel_facts = _channel_facts(channel)
        sample = _sample_metrics(videos)
        limitations: list[str] = []
        if channel_facts["hidden_subscriber_count"]:
            limitations.append("The channel hides its subscriber count; views-to-subscribers ratios were not calculated.")
        if len(videos) < request.max_videos:
            limitations.append(f"Only {len(videos)} accessible recent videos were returned by the official API.")
        sources = [
            SourceReference(
                url=f"https://www.youtube.com/channel/{channel_facts['channel_id']}",
                source_type="youtube_channel",
                external_id=channel_facts["channel_id"],
                title=channel_facts["title"],
                published_at=_parse_datetime(channel_facts.get("published_at")),
                fact="YouTube Data API channel metadata and statistics.",
            )
        ]
        for video in videos:
            facts = _video_facts(video)
            sources.append(
                SourceReference(
                    url=f"https://www.youtube.com/watch?v={facts['video_id']}",
                    source_type="youtube_video",
                    external_id=facts["video_id"],
                    title=facts["title"],
                    published_at=_parse_datetime(facts.get("published_at")),
                    fact="Recent channel video included in the comparison sample.",
                )
            )
        insights = {
            "breakout_video_ids": [row["video_id"] for row in sample["breakout_videos"]],
            "comparison_basis": "Breakout means more than 2x this channel sample's median views; it is not a universal success threshold.",
            "analysis_basis": "Channel and video metadata/statistics only; no frame, editing, or audio analysis was performed.",
        }
        return _finish_analysis(
            db,
            analysis,
            summary=f"Analyzed channel '{channel_facts['title']}' and {len(videos)} recent accessible videos.",
            facts={"channel": channel_facts, "videos": sample["videos"]},
            insights=insights,
            metrics={key: value for key, value in sample.items() if key != "videos" and key != "breakout_videos"},
            limitations=limitations,
            sources=sources,
        )
    except YouTubeGrowthError as exc:
        _fail_analysis(db, analysis, exc)
        raise


def _competitor_score(query: str, sample: dict[str, Any]) -> GrowthScoreBreakdown:
    rows = sample.get("videos") if isinstance(sample.get("videos"), list) else []
    views = [max(0, row["views"]) for row in rows if isinstance(row.get("views"), int)]
    max_views = max(views, default=0)
    median_views = _float(sample.get("median_views"))
    demand = round((median_views / max_views) * 100) if max_views else 0
    breakout_count = len(sample.get("breakout_videos") or [])
    competition_gap = round(100 * breakout_count / len(rows)) if rows else 0
    title_questions = sum(1 for row in rows if "?" in str(row.get("title") or ""))
    hook_strength = round(100 * title_questions / len(rows)) if rows else 0
    titled = sum(1 for row in rows if str(row.get("title") or "").strip())
    packaging = round(50 * titled / len(rows)) if rows else 0
    published_dates = [_parse_datetime(row.get("published_at")) for row in rows]
    recent = sum(1 for published in published_dates if published and published >= datetime.now(UTC) - timedelta(days=90))
    timing = round(100 * recent / len(rows)) if rows else 0
    components = GrowthScoreComponents(
        topic_demand=ScoreComponent(score=demand, explanation="Relative median views compared with the largest video in this sample."),
        competition_gap=ScoreComponent(score=competition_gap, explanation="Share of sample videos breaking above 2x the sample median."),
        hook_strength=ScoreComponent(score=hook_strength, explanation="Title-level hook signal only; scripts and frames were not inspected."),
        title_thumbnail_packaging=ScoreComponent(
            score=packaging,
            explanation=(
                "Title completeness only. Thumbnail creative was not visually inspected, so this component is capped at 50."
            ),
        ),
        channel_fit=ScoreComponent(score=50, explanation="Neutral until the user's own channel history is available for calibration."),
        timing_relevance=ScoreComponent(score=timing, explanation="Share of sample videos published in the last 90 days, relative to this sample."),
    )
    return calculate_growth_opportunity_score(query, components)


TITLE_TOKEN_RE = re.compile(r"[\w-]{3,}", re.UNICODE)
TITLE_STOPWORDS = {
    "and", "are", "but", "for", "from", "how", "into", "the", "this", "that", "with", "you", "your",
    "как", "для", "или", "что", "это", "эта", "эти", "при", "про", "под", "над", "без",
}


def _sample_content_signals(sample: dict[str, Any]) -> dict[str, Any]:
    rows = sample.get("videos") if isinstance(sample.get("videos"), list) else []
    breakout_rows = sample.get("breakout_videos") if isinstance(sample.get("breakout_videos"), list) else []
    breakout_ids = {str(row.get("video_id") or "") for row in breakout_rows if isinstance(row, dict)}
    all_terms: Counter[str] = Counter()
    breakout_terms: Counter[str] = Counter()
    patterns: Counter[str] = Counter()
    cta_signals: Counter[str] = Counter()
    for row in rows:
        title = str(row.get("title") or "")
        lowered = title.lower()
        terms = {
            token.casefold()
            for token in TITLE_TOKEN_RE.findall(lowered)
            if token.casefold() not in TITLE_STOPWORDS and not token.isdigit()
        }
        all_terms.update(terms)
        if str(row.get("video_id") or "") in breakout_ids:
            breakout_terms.update(terms)
        if "?" in title:
            patterns["question"] += 1
        if re.search(r"\bhow\s+to\b|\bкак\s+", lowered):
            patterns["how_to"] += 1
        if re.search(r"\b\d+\b", title):
            patterns["numbered"] += 1
        description = str(row.get("description") or "").casefold()
        for signal, variants in {
            "subscribe": ("subscribe", "подпиш"),
            "comment": ("comment", "коммент"),
            "description_link": ("link in description", "ссылка в описании"),
        }.items():
            if any(variant in description for variant in variants):
                cta_signals[signal] += 1
    sample_size = len(rows)
    repeated_topics = [
        {
            "term": term,
            "video_count": count,
            "sample_share": round(count / sample_size, 4) if sample_size else 0,
            "basis": "Case-insensitive title-token frequency in this API sample.",
        }
        for term, count in all_terms.most_common(12)
        if count >= 2
    ][:8]
    max_gap_coverage = max(2, round(sample_size * 0.3))
    content_gaps = []
    for term, breakout_count in breakout_terms.most_common():
        total_count = all_terms[term]
        if total_count <= max_gap_coverage and breakout_count >= 1:
            content_gaps.append(
                {
                    "term": term,
                    "breakout_video_count": breakout_count,
                    "total_video_count": total_count,
                    "interpretation": (
                        "Sample-relative hypothesis: this underrepresented title term appears in a breakout video. "
                        "It is not proof of unmet demand and should be validated with more research."
                    ),
                }
            )
        if len(content_gaps) >= 8:
            break
    return {
        "repeated_topics": repeated_topics,
        "content_gap_hypotheses": content_gaps,
        "title_format_signals": [
            {"pattern": pattern, "video_count": count, "sample_share": round(count / sample_size, 4)}
            for pattern, count in patterns.most_common()
        ],
        "description_cta_signals": [
            {"signal": signal, "video_count": count, "sample_share": round(count / sample_size, 4)}
            for signal, count in cta_signals.most_common()
        ],
    }


async def analyze_competitors(
    db: Session,
    settings: Settings,
    user: User,
    workspace_id: int,
    request: CompetitorAnalysisRequest,
) -> AnalysisResponse:
    credentials = load_youtube_credentials(db, user, account_id=request.account_id, required=False)
    analysis = _begin_analysis(
        db,
        user,
        workspace_id,
        kind="competitors",
        target_url=f"https://www.youtube.com/results?search_query={request.query}",
        target_id=request.query,
        account_id=credentials.account_id if credentials else None,
        request_json=request.model_dump(mode="json"),
        idempotency_key=request.idempotency_key,
    )
    if analysis.status != "running":
        return analysis_response(db, analysis)
    client = YouTubeClient(
        db,
        settings,
        workspace_id=workspace_id,
        integration_account_id=credentials.account_id if credentials else None,
        access_token=credentials.access_token if credentials else None,
    )
    try:
        searched_videos = await client.search_videos(
            request.query,
            max_videos=request.limit,
            language=request.language,
            region=request.region,
        )
        limitations: list[str] = []
        regional_trending_matches: list[dict[str, Any]] = []
        if request.region:
            try:
                regional_trending = await client.trending_videos(request.region, min(20, request.limit))
                query_terms = {
                    token.casefold()
                    for token in TITLE_TOKEN_RE.findall(request.query)
                    if token.casefold() not in TITLE_STOPWORDS
                }
                regional_trending_matches = [
                    video
                    for video in regional_trending
                    if query_terms.intersection(
                        TITLE_TOKEN_RE.findall(str(_video_facts(video).get("title") or "").casefold())
                    )
                ]
            except YouTubeGrowthError as exc:
                limitations.append(f"Regional trending videos were unavailable: {exc.message}")
        videos_by_id: dict[str, dict[str, Any]] = {}
        for video in [*regional_trending_matches, *searched_videos]:
            video_id = str(_video_facts(video).get("video_id") or "")
            if video_id:
                videos_by_id.setdefault(video_id, video)
        videos = list(videos_by_id.values())[: request.limit]
        channel_ids = [str(_video_facts(video).get("channel_id") or "") for video in videos]
        channels = {str(channel.get("id") or ""): channel for channel in await client.get_channels(channel_ids)}
        sample = _sample_metrics(videos, channels)
        if len(videos) < 10:
            limitations.append(f"Only {len(videos)} relevant accessible videos were returned; competitor conclusions are partial.")
        hidden_channels = sum(1 for channel in channels.values() if _channel_facts(channel)["hidden_subscriber_count"])
        if hidden_channels:
            limitations.append(f"{hidden_channels} sampled channels hide subscriber counts; their views-to-subscribers ratios are unavailable.")
        sources: list[SourceReference] = []
        trending_ids = {
            str(_video_facts(video).get("video_id") or "") for video in regional_trending_matches
        }
        for video in videos:
            facts = _video_facts(video)
            sources.append(
                SourceReference(
                    url=f"https://www.youtube.com/watch?v={facts['video_id']}",
                    source_type=(
                        "regional_trending_video" if facts["video_id"] in trending_ids else "competitor_video"
                    ),
                    external_id=facts["video_id"],
                    title=facts["title"],
                    published_at=_parse_datetime(facts.get("published_at")),
                    fact="Video included in the official YouTube search result sample.",
                )
            )
        score = _competitor_score(request.query, sample)
        content_signals = _sample_content_signals(sample)
        insights = {
            "breakout_video_ids": [row["video_id"] for row in sample["breakout_videos"]],
            "regional_trending_match_ids": sorted(trending_ids.intersection(videos_by_id)),
            "repeated_topics": content_signals["repeated_topics"],
            "content_gaps": content_signals["content_gap_hypotheses"],
            "title_format_signals": content_signals["title_format_signals"],
            "description_cta_signals": content_signals["description_cta_signals"],
            "interpretation_note": "Breakout detection is sample-relative. Topic and content-gap interpretation requires the validated content strategist step.",
            "analysis_basis": "Public metadata/statistics only; no video files, frames, editing, or audio were analyzed.",
        }
        metrics = {key: value for key, value in sample.items() if key not in {"videos", "breakout_videos"}}
        return _finish_analysis(
            db,
            analysis,
            summary=f"Compared {len(videos)} relevant videos for '{request.query}' using official API data.",
            facts={"query": request.query, "videos": sample["videos"]},
            insights=insights,
            metrics=metrics,
            limitations=limitations,
            sources=sources,
            score=score,
        )
    except YouTubeGrowthError as exc:
        _fail_analysis(db, analysis, exc)
        raise


def plan_response(db: Session, plan: YouTubeContentPlan) -> ContentPlanResponse:
    records = db.scalars(
        select(YouTubeContentPlanItem)
        .where(YouTubeContentPlanItem.plan_id == plan.id, YouTubeContentPlanItem.workspace_id == plan.workspace_id)
        .order_by(YouTubeContentPlanItem.position)
    ).all()
    item_records = [_plan_item_response(record) for record in records]
    return ContentPlanResponse(
        id=plan.id,
        status=plan.status,
        days=plan.horizon_days,
        items=[record.item for record in item_records],
        item_records=item_records,
        score_breakdowns=[record.score_breakdown for record in item_records],
        disclaimer=GROWTH_SCORE_DISCLAIMER,
        limitations=[str(item) for item in (plan.limitations_json or [])],
        error=plan.error,
        created_at=plan.created_at,
    )


def _plan_item_breakdown(record: YouTubeContentPlanItem) -> GrowthScoreBreakdown:
    payload = dict(record.score_components_json or {})
    payload.setdefault("topic", str((record.item_json or {}).get("topic") or "Content idea"))
    payload.setdefault("total_score", record.opportunity_score)
    payload.setdefault(
        "explanation",
        str((record.item_json or {}).get("score_explanation") or "Weighted score components."),
    )
    return GrowthScoreBreakdown.model_validate(payload)


def _plan_item_response(record: YouTubeContentPlanItem) -> ContentPlanItemResponse:
    return ContentPlanItemResponse(
        id=record.id,
        plan_id=record.plan_id,
        position=record.position,
        approved=record.approved,
        item=ContentPlanItem.model_validate(record.item_json),
        score_breakdown=_plan_item_breakdown(record),
        updated_at=record.updated_at,
    )


def _sync_plan_result(db: Session, plan: YouTubeContentPlan) -> None:
    records = db.scalars(
        select(YouTubeContentPlanItem)
        .where(
            YouTubeContentPlanItem.plan_id == plan.id,
            YouTubeContentPlanItem.workspace_id == plan.workspace_id,
        )
        .order_by(YouTubeContentPlanItem.position)
    ).all()
    plan.result_json = {
        "items": [dict(record.item_json) for record in records],
        "score_breakdowns": [_plan_item_breakdown(record).model_dump(mode="json") for record in records],
        "disclaimer": GROWTH_SCORE_DISCLAIMER,
    }


def update_content_plan_item(
    db: Session,
    user: User,
    plan_id: int,
    item_id: int,
    request: ContentPlanItemPatchRequest,
) -> ContentPlanItemResponse:
    """Persist a validated user edit or approval without publishing content."""

    plan = db.get(YouTubeContentPlan, plan_id)
    if plan is None:
        raise YouTubeNotFoundError("YouTube content plan was not found.")
    context = get_workspace_context(db, user, plan.workspace_id)
    require_workspace_role(context.member, WRITE_ROLES)
    record = db.scalar(
        select(YouTubeContentPlanItem).where(
            YouTubeContentPlanItem.id == item_id,
            YouTubeContentPlanItem.plan_id == plan.id,
            YouTubeContentPlanItem.workspace_id == plan.workspace_id,
        )
    )
    if record is None:
        raise YouTubeNotFoundError("YouTube content plan item was not found.")

    changes = request.model_dump(exclude_unset=True)
    approved = changes.pop("approved", None)
    submitted_components = changes.pop("score_components", None)
    merged = dict(record.item_json)
    merged.update(changes)
    validated_item = ContentPlanItem.model_validate(merged)

    if submitted_components is not None:
        components = GrowthScoreComponents.model_validate(submitted_components)
        breakdown = calculate_growth_opportunity_score(validated_item.topic, components)
        validated_item = validated_item.model_copy(
            update={
                "opportunity_score": breakdown.total_score,
                "score_explanation": breakdown.explanation,
            }
        )
        record.score_components_json = breakdown.model_dump(mode="json")
        record.opportunity_score = breakdown.total_score
    else:
        breakdown = _plan_item_breakdown(record).model_copy(update={"topic": validated_item.topic})
        record.score_components_json = breakdown.model_dump(mode="json")

    record.item_json = validated_item.model_dump(mode="json")
    record.publish_date = validated_item.publish_date.isoformat()
    record.confidence = validated_item.confidence
    if approved is not None:
        record.approved = approved
    db.flush()
    _sync_plan_result(db, plan)
    db.commit()
    db.refresh(record)
    return _plan_item_response(record)


async def create_content_plan(
    db: Session,
    settings: Settings,
    user: User,
    workspace_id: int,
    request: ContentPlanCreateRequest,
    *,
    model_client: JsonModelClient | None = None,
) -> ContentPlanResponse:
    if request.idempotency_key:
        existing = db.scalar(
            select(YouTubeContentPlan).where(
                YouTubeContentPlan.workspace_id == workspace_id,
                YouTubeContentPlan.idempotency_key == request.idempotency_key,
            )
        )
        if existing:
            if existing.status in {"queued", "running"}:
                raise OperationInProgressError("This YouTube content plan is already in progress.")
            return plan_response(db, existing)
    analyses = []
    if request.analysis_ids:
        analyses = db.scalars(
            select(YouTubeAnalysisRun).where(
                YouTubeAnalysisRun.workspace_id == workspace_id,
                YouTubeAnalysisRun.id.in_(request.analysis_ids),
            )
        ).all()
        if len(analyses) != len(set(request.analysis_ids)):
            raise YouTubePermissionError("One or more selected analyses are outside this workspace or do not exist.")
    credentials = load_youtube_credentials(db, user, account_id=request.account_id, required=False)
    plan = YouTubeContentPlan(
        workspace_id=workspace_id,
        created_by=user.id,
        source_analysis_id=analyses[0].id if analyses else None,
        integration_account_id=credentials.account_id if credentials else None,
        horizon_days=request.days,
        niche=request.niche,
        language=request.language,
        region=request.region,
        goal=request.goal,
        status="running",
        request_json=request.model_dump(mode="json"),
        model_name=settings.youtube_llm_model or None,
        idempotency_key=request.idempotency_key,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    sources = []
    if analyses:
        sources = db.scalars(
            select(YouTubeAnalysisSource).where(
                YouTubeAnalysisSource.workspace_id == workspace_id,
                YouTubeAnalysisSource.analysis_id.in_([analysis.id for analysis in analyses]),
            )
        ).all()
    allowed_sources = list(dict.fromkeys(source.url for source in sources if source.url.startswith("https://")))
    context = [
        {
            "analysis_id": analysis.id,
            "kind": analysis.kind,
            "facts": (analysis.result_json or {}).get("facts", {}),
            "insights": (analysis.result_json or {}).get("insights", {}),
            "limitations": analysis.limitations_json or [],
            "trust": "untrusted_external_data",
        }
        for analysis in analyses
    ]
    limitations = []
    if not analyses:
        limitations.append("No prior YouTube analysis was selected; the plan is based only on user-provided strategy inputs.")
    elif any(analysis.partial for analysis in analyses):
        limitations.append("One or more source analyses were partial; review their limitations before publishing.")
    try:
        client = model_client or HttpJsonModelClient(settings)
        generated = await generate_validated_content_plan(client, request, context, allowed_sources)
        breakdowns: list[GrowthScoreBreakdown] = []
        item_payloads = []
        for position, entry in enumerate(generated.plan.items):
            breakdown = calculate_growth_opportunity_score(entry.item.topic, entry.score_components)
            final_item = entry.item.model_copy(
                update={
                    "opportunity_score": breakdown.total_score,
                    "score_explanation": breakdown.explanation,
                }
            )
            item_json = final_item.model_dump(mode="json")
            db.add(
                YouTubeContentPlanItem(
                    workspace_id=workspace_id,
                    plan_id=plan.id,
                    position=position,
                    publish_date=final_item.publish_date.isoformat(),
                    item_json=item_json,
                    score_components_json=breakdown.model_dump(mode="json"),
                    opportunity_score=breakdown.total_score,
                    confidence=final_item.confidence,
                )
            )
            item_payloads.append(item_json)
            breakdowns.append(breakdown)
        plan.status = "completed"
        plan.repair_attempts = generated.repair_attempts
        plan.limitations_json = limitations
        plan.result_json = {
            "items": item_payloads,
            "score_breakdowns": [breakdown.model_dump(mode="json") for breakdown in breakdowns],
            "disclaimer": GROWTH_SCORE_DISCLAIMER,
        }
        plan.completed_at = datetime.now(UTC)
        db.commit()
        db.refresh(plan)
        return plan_response(db, plan)
    except (YouTubeGrowthError, ModelUnavailableError) as exc:
        plan.status = "failed"
        plan.error = exc.message
        plan.completed_at = datetime.now(UTC)
        db.commit()
        raise


def _checkpoint_window(checkpoint: str) -> timedelta:
    return {
        "1h": timedelta(hours=1),
        "6h": timedelta(hours=6),
        "24h": timedelta(hours=24),
        "72h": timedelta(hours=72),
        "7d": timedelta(days=7),
    }[checkpoint]


def _checkpoint_end_date(published_at: datetime, checkpoint: str) -> date:
    whole_days = max(1, round(_checkpoint_window(checkpoint).total_seconds() / 86_400))
    return published_at.date() + timedelta(days=whole_days - 1)


def _bounded_analytics_rows(
    rows: list[dict[str, Any]],
    *,
    dimension: str,
    metrics: tuple[str, ...],
    limit: int,
) -> list[dict[str, Any]]:
    """Keep only documented columns and a bounded number of facet rows.

    Analytics dimension labels are API data, not instructions. Keeping the
    response narrow also prevents a high-cardinality report from making a
    growth snapshot or its model context unbounded.
    """

    result: list[dict[str, Any]] = []
    for row in rows:
        dimension_value = row.get(dimension)
        if dimension_value is None or dimension_value == "":
            continue
        item: dict[str, Any] = {dimension: str(dimension_value)[:100]}
        for metric in metrics:
            value = row.get(metric)
            if value is not None:
                item[metric] = value
        result.append(item)
    result.sort(key=lambda item: _float(item.get("views")), reverse=True)
    return result[:limit]


async def _growth_analytics_facets(
    client: YouTubeClient,
    credentials: YouTubeCredentials,
    *,
    video_id: str,
    start_date: date,
    end_date: date,
) -> tuple[dict[str, Any], list[str]]:
    """Fetch optional official Analytics facets without inventing values."""

    facets: dict[str, Any] = {}
    limitations: list[str] = []

    try:
        channel = await client.resolve_channel(credentials.channel_id)
        facts = _channel_facts(channel)
        facets["channel_context"] = {
            "channel_id": facts["channel_id"],
            "title": facts["title"],
            "country": facts["country"],
            "subscriber_count": facts["subscriber_count"],
            "hidden_subscriber_count": facts["hidden_subscriber_count"],
            "view_count": facts["view_count"],
            "video_count": facts["video_count"],
        }
    except YouTubeGrowthError as exc:
        limitations.append(f"Connected-channel context was unavailable: {exc.message}")

    try:
        retention_rows = await client.analytics_report(
            start_date=start_date,
            end_date=end_date,
            metrics=["averageViewPercentage"],
            video_id=video_id,
        )
        retention_value = retention_rows[0].get("averageViewPercentage") if retention_rows else None
        if retention_value is not None:
            facets["averageViewPercentage"] = retention_value
        else:
            limitations.append("Average view percentage was not returned for this video/checkpoint and was omitted.")
    except AnalyticsUnavailableError:
        limitations.append("Average view percentage is unavailable for this account/video and was omitted.")

    facet_specs = (
        ("traffic_sources", "insightTrafficSourceType", 25),
        ("geography", "country", 25),
        ("devices", "deviceType", 20),
    )
    facet_metrics = ("views", "estimatedMinutesWatched")
    for key, dimension, limit in facet_specs:
        try:
            rows = await client.analytics_report(
                start_date=start_date,
                end_date=end_date,
                metrics=list(facet_metrics),
                video_id=video_id,
                dimensions=[dimension],
            )
            bounded = _bounded_analytics_rows(
                rows,
                dimension=dimension,
                metrics=facet_metrics,
                limit=limit,
            )
            if bounded:
                facets[key] = bounded
            else:
                limitations.append(f"YouTube Analytics returned no {key.replace('_', ' ')} rows for this checkpoint.")
        except AnalyticsUnavailableError:
            limitations.append(f"YouTube Analytics {key.replace('_', ' ')} are unavailable and were omitted.")

    audience_metrics = ("views", "estimatedMinutesWatched", "averageViewDuration", "averageViewPercentage")
    try:
        rows = await client.analytics_report(
            start_date=start_date,
            end_date=end_date,
            metrics=list(audience_metrics),
            video_id=video_id,
            dimensions=["subscribedStatus"],
        )
        bounded = _bounded_analytics_rows(
            rows,
            dimension="subscribedStatus",
            metrics=audience_metrics,
            limit=5,
        )
        if bounded:
            facets["audience_by_subscription"] = bounded
        else:
            limitations.append("YouTube Analytics returned no subscribed/unsubscribed audience context.")
    except AnalyticsUnavailableError:
        limitations.append("Subscribed/unsubscribed audience context is unavailable and was omitted.")

    # The targeted YouTube Analytics reports used by this service do not expose
    # Studio's returning-viewers metric. Subscription status is useful context,
    # but it must never be presented as a returning-viewer estimate.
    facets["returning_viewers"] = {
        "available": False,
        "value": None,
        "reason": "Not exposed by the supported YouTube Analytics targeted-query reports.",
    }
    limitations.append(
        "Returning viewers are not exposed by the supported YouTube Analytics targeted-query reports; "
        "subscribed/unsubscribed audience context is shown instead when available."
    )
    return facets, limitations


async def _comparable_video_baseline(
    client: YouTubeClient,
    credentials: YouTubeCredentials,
    request: GrowthSnapshotCreateRequest,
    core_metrics: list[str],
) -> tuple[dict[str, Any], list[str]]:
    limitations: list[str] = []
    if request.checkpoint in {"1h", "6h"}:
        return (
            {"sample_size": 0, "comparison_window": request.checkpoint},
            [
                "YouTube Analytics exposes daily aggregates through this API, so an honest channel baseline is unavailable for the 1h/6h checkpoint. No early comparative recommendation was generated."
            ],
        )
    try:
        channel = await client.resolve_channel(credentials.channel_id)
        candidates = await client.channel_videos(channel, request.baseline_video_count + 1)
    except YouTubeGrowthError as exc:
        return (
            {"sample_size": 0, "comparison_window": request.checkpoint},
            [f"Comparable owned-video baseline was unavailable: {exc.message}"],
        )
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        facts = _video_facts(candidate)
        candidate_id = str(facts.get("video_id") or "")
        published = _parse_datetime(facts.get("published_at"))
        if not candidate_id or candidate_id == request.video_id or published is None:
            continue
        try:
            reports = await client.analytics_report(
                start_date=published.date(),
                end_date=_checkpoint_end_date(published, request.checkpoint),
                metrics=core_metrics,
                video_id=candidate_id,
            )
        except YouTubeGrowthError:
            continue
        if reports:
            rows.append(reports[0])
        if len(rows) >= request.baseline_video_count:
            break
    baseline: dict[str, Any] = {
        "sample_size": len(rows),
        "comparison_window": request.checkpoint,
        "basis": "Owned-channel videos measured over the same API-supported post-publication day window.",
    }
    for metric in core_metrics:
        values = [_float(row.get(metric)) for row in rows if row.get(metric) is not None]
        baseline[metric] = round(statistics.fmean(values), 4) if values else None
    if not rows:
        limitations.append("No comparable owned videos with analytics were returned; comparative recommendations were omitted.")
    if request.checkpoint == "24h":
        limitations.append("The 24h comparison uses YouTube Analytics daily buckets and is an approximation, not an exact rolling 24-hour window.")
    return baseline, limitations


async def create_growth_snapshot(
    db: Session,
    settings: Settings,
    user: User,
    workspace_id: int,
    request: GrowthSnapshotCreateRequest,
) -> GrowthSnapshotResponse:
    credentials = load_youtube_credentials(db, user, account_id=request.account_id, required=True)
    assert credentials is not None
    if not credentials.can_analyze_private_metrics:
        raise YouTubePermissionError(
            "Reconnect YouTube and grant YouTube Analytics readonly permission for private performance metrics."
        )
    existing = db.scalar(
        select(YouTubeGrowthSnapshot).where(
            YouTubeGrowthSnapshot.workspace_id == workspace_id,
            YouTubeGrowthSnapshot.integration_account_id == credentials.account_id,
            YouTubeGrowthSnapshot.video_id == request.video_id,
            YouTubeGrowthSnapshot.checkpoint == request.checkpoint,
        )
    )
    if existing and existing.status in {"completed", "partial"}:
        return snapshot_response(existing)
    client = YouTubeClient(
        db,
        settings,
        workspace_id=workspace_id,
        integration_account_id=credentials.account_id,
        access_token=credentials.access_token,
    )
    snapshot = existing
    try:
        video = await client.get_video(request.video_id, require_oauth=True)
        facts = _video_facts(video)
        if facts.get("channel_id") != credentials.channel_id:
            raise YouTubePermissionError("Growth snapshots are available only for videos owned by the connected channel.")
        published = _parse_datetime(facts.get("published_at"))
        preflight_limitations: list[str] = []
        if published is None:
            published = datetime.now(UTC) - _checkpoint_window(request.checkpoint)
            preflight_limitations.append(
                "The video publication timestamp was unavailable; checkpoint scheduling could not be reconstructed exactly."
            )
        scheduled_for = published + _checkpoint_window(request.checkpoint)
        snapshot = existing or YouTubeGrowthSnapshot(
            workspace_id=workspace_id,
            created_by=user.id,
            integration_account_id=credentials.account_id,
            video_id=request.video_id,
            checkpoint=request.checkpoint,
            status="queued",
            scheduled_for=scheduled_for,
        )
        snapshot.scheduled_for = scheduled_for
        if existing is None:
            db.add(snapshot)
        if datetime.now(UTC) < scheduled_for:
            snapshot.status = "queued"
            snapshot.metrics_json = {}
            snapshot.baseline_json = {}
            snapshot.recommendations_json = []
            snapshot.limitations_json = [
                *preflight_limitations,
                "Analytics collection is queued until the selected post-publication checkpoint is reached.",
            ]
            db.commit()
            db.refresh(snapshot)
            return snapshot_response(snapshot)
        snapshot.status = "running"
        db.commit()
        db.refresh(snapshot)
        start_date = published.date()
        end_date = min(date.today(), _checkpoint_end_date(published, request.checkpoint))
        core_metrics = [
            "views",
            "estimatedMinutesWatched",
            "averageViewDuration",
            "likes",
            "comments",
            "subscribersGained",
            "subscribersLost",
        ]
        rows = await client.analytics_report(
            start_date=start_date,
            end_date=end_date,
            metrics=core_metrics,
            video_id=request.video_id,
        )
        metrics = rows[0] if rows else {}
        limitations: list[str] = list(preflight_limitations)
        if not rows:
            limitations.append("YouTube Analytics returned no metrics for this checkpoint.")
        try:
            packaging_rows = await client.analytics_report(
                start_date=start_date,
                end_date=end_date,
                metrics=["videoThumbnailImpressions", "videoThumbnailImpressionsClickRate"],
                video_id=request.video_id,
            )
            if packaging_rows:
                metrics.update(packaging_rows[0])
            else:
                limitations.append("Impressions and CTR were not returned for this video.")
        except AnalyticsUnavailableError:
            limitations.append("Impressions and CTR are unavailable for this account/video and were omitted.")
        facets, facet_limitations = await _growth_analytics_facets(
            client,
            credentials,
            video_id=request.video_id,
            start_date=start_date,
            end_date=end_date,
        )
        metrics.update(facets)
        limitations.extend(facet_limitations)
        baseline_metrics = list(core_metrics)
        if metrics.get("averageViewPercentage") is not None:
            baseline_metrics.append("averageViewPercentage")
        baseline, baseline_limitations = await _comparable_video_baseline(
            client,
            credentials,
            request,
            baseline_metrics,
        )
        limitations.extend(baseline_limitations)
        recommendations: list[str] = []
        if baseline["sample_size"] > 0:
            for metric, label in (
                ("views", "view velocity"),
                ("estimatedMinutesWatched", "watch time"),
                ("averageViewDuration", "average view duration"),
                ("averageViewPercentage", "average view percentage"),
            ):
                current_value = metrics.get(metric)
                average = baseline.get(metric)
                if current_value is not None and isinstance(average, (int, float)) and average > 0:
                    current = _float(current_value)
                    if current < average:
                        recommendations.append(f"{label.title()} is below this channel's comparable-video baseline; test the packaging or opening hook.")
                    else:
                        recommendations.append(f"{label.title()} is at or above this channel's baseline; preserve the effective topic and format signals.")
        snapshot.metrics_json = metrics
        snapshot.baseline_json = baseline
        snapshot.recommendations_json = recommendations
        snapshot.limitations_json = limitations
        snapshot.status = "partial" if limitations else "completed"
        snapshot.observed_at = datetime.now(UTC)
        db.commit()
        db.refresh(snapshot)
        return snapshot_response(snapshot)
    except YouTubeGrowthError as exc:
        if snapshot is not None:
            snapshot.status = "failed"
            snapshot.error_code = exc.code
            snapshot.error = exc.message
            snapshot.observed_at = datetime.now(UTC)
            db.commit()
        raise


def snapshot_response(snapshot: YouTubeGrowthSnapshot) -> GrowthSnapshotResponse:
    return GrowthSnapshotResponse(
        id=snapshot.id,
        video_id=snapshot.video_id,
        checkpoint=snapshot.checkpoint,
        status=snapshot.status,
        metrics=snapshot.metrics_json or {},
        baseline=snapshot.baseline_json or {},
        recommendations=[str(item) for item in (snapshot.recommendations_json or [])],
        limitations=[str(item) for item in (snapshot.limitations_json or [])],
        sources=[
            SourceReference(
                url=f"https://www.youtube.com/watch?v={snapshot.video_id}",
                source_type="owned_youtube_video_analytics",
                external_id=snapshot.video_id,
                fact="YouTube Data API metadata and authorized YouTube Analytics API metrics.",
            )
        ],
        error_code=snapshot.error_code,
        error=snapshot.error,
        scheduled_for=_as_utc(snapshot.scheduled_for),
        observed_at=_as_utc(snapshot.observed_at),
        created_at=_as_utc(snapshot.created_at),
    )


def recommendations(db: Session, workspace_id: int, video_id: str | None = None) -> list[GrowthSnapshotResponse]:
    query = select(YouTubeGrowthSnapshot).where(YouTubeGrowthSnapshot.workspace_id == workspace_id)
    if video_id:
        query = query.where(YouTubeGrowthSnapshot.video_id == video_id)
    records = db.scalars(query.order_by(YouTubeGrowthSnapshot.created_at.desc()).limit(100)).all()
    return [snapshot_response(record) for record in records]


def overview(
    db: Session,
    settings: Settings,
    user: User,
    workspace_id: int,
) -> YouTubeOverviewResponse:
    account_statuses = list_youtube_account_statuses(db, user)
    connected = any(account.connected for account in account_statuses)
    missing: list[str] = []
    if not any(account.can_read for account in account_statuses):
        missing.append("youtube.readonly")
    if not any(account.can_analyze_private_metrics for account in account_statuses):
        missing.append("yt-analytics.readonly")
    analyses = db.scalars(
        select(YouTubeAnalysisRun)
        .where(YouTubeAnalysisRun.workspace_id == workspace_id)
        .order_by(YouTubeAnalysisRun.created_at.desc())
        .limit(10)
    ).all()
    plans = db.scalars(
        select(YouTubeContentPlan)
        .where(YouTubeContentPlan.workspace_id == workspace_id, YouTubeContentPlan.status == "completed")
        .order_by(YouTubeContentPlan.created_at.desc())
        .limit(5)
    ).all()
    return YouTubeOverviewResponse(
        workspace_id=workspace_id,
        public_research_available=bool(settings.youtube_api_key.strip() or any(account.can_read for account in account_statuses)),
        connected=connected,
        connection_state="connected" if connected else "not_connected",
        accounts=account_statuses,
        missing_permissions=missing,
        recent_analyses=[analysis_response(db, analysis) for analysis in analyses],
        recent_plans=[plan_response(db, plan) for plan in plans],
        disclaimer=GROWTH_SCORE_DISCLAIMER,
    )


DELEGATE_ROLES: dict[str, tuple[tuple[str, str], ...]] = {
    "analyze_video": (("Video Analyst", "youtube-video-analyst"),),
    "analyze_channel": (
        ("Video Analyst", "youtube-video-analyst"),
        ("Growth Analyst", "youtube-growth-analyst"),
    ),
    "analyze_competitors": (
        ("Trend Scout", "youtube-trend-scout"),
        ("Competitor Analyst", "youtube-competitor-analyst"),
    ),
    "create_content_plan": (
        ("Content Strategist", "youtube-content-strategist"),
        ("Creative Director", "youtube-creative-director"),
    ),
    "growth_snapshot": (("Growth Analyst", "youtube-growth-analyst"),),
}


def _delegated_task_response(db: Session, coordinator_task: Task) -> DelegateResponse:
    payload = coordinator_task.input_json or {}
    children = db.scalars(
        select(Task)
        .where(
            Task.parent_task_id == coordinator_task.id,
            Task.workspace_id == coordinator_task.workspace_id,
            Task.created_by == coordinator_task.created_by,
        )
        .order_by(Task.id)
    ).all()
    return DelegateResponse(
        coordinator_task_id=coordinator_task.id,
        child_tasks=[
            DelegatedTask(id=child.id, role=str((child.input_json or {}).get("role")), status=child.status)
            for child in children
        ],
        artifact_ids=[int(value) for value in payload.get("artifactIds", [])],
        status="queued",
        message="Atlas queued the request and assigned authenticated workspace tasks. No external publish action was performed.",
    )


def _find_idempotent_delegation(
    db: Session,
    *,
    workspace_id: int,
    user_id: int,
    team_id: int,
    request: DelegateRequest,
) -> DelegateResponse | None:
    if request.idempotency_key is None:
        return None
    candidates = db.scalars(
        select(Task)
        .where(
            Task.workspace_id == workspace_id,
            Task.created_by == user_id,
            Task.team_id == team_id,
            Task.parent_task_id.is_(None),
        )
        .order_by(Task.id.desc())
    ).all()
    for candidate in candidates:
        payload = candidate.input_json or {}
        if payload.get("source") != "youtube_growth_delegate":
            continue
        if payload.get("idempotencyKey") != request.idempotency_key:
            continue
        if (
            payload.get("action") != request.action
            or payload.get("input", {}) != request.input
            or payload.get("artifactIds", []) != request.artifact_ids
        ):
            raise IdempotencyConflictError()
        return _delegated_task_response(db, candidate)
    return None


def delegate_to_youtube_team(db: Session, user: User, request: DelegateRequest) -> DelegateResponse:
    context = get_workspace_context(db, user, request.workspace_id)
    require_workspace_role(context.member, WRITE_ROLES)
    # Delegation is the one read-like path that depends on the current default
    # team catalogue.  Seed lazily here so ordinary workspace reads remain
    # cheap while legacy/imported workspaces still gain the YouTube team before
    # a delegation is created.
    seed_default_workspace(db, context.workspace, created_by=user.id)
    team = db.scalar(
        select(Team).where(Team.workspace_id == context.workspace.id, Team.slug == "youtube-growth-team")
    )
    if team is None:
        raise YouTubeTeamUnavailableError()
    existing = _find_idempotent_delegation(
        db,
        workspace_id=context.workspace.id,
        user_id=user.id,
        team_id=team.id,
        request=request,
    )
    if existing is not None:
        return existing
    if request.artifact_ids:
        analysis_ids = set(
            db.scalars(
                select(YouTubeAnalysisRun.id).where(
                    YouTubeAnalysisRun.workspace_id == context.workspace.id,
                    YouTubeAnalysisRun.id.in_(request.artifact_ids),
                )
            ).all()
        )
        plan_ids = set(
            db.scalars(
                select(YouTubeContentPlan.id).where(
                    YouTubeContentPlan.workspace_id == context.workspace.id,
                    YouTubeContentPlan.id.in_(request.artifact_ids),
                )
            ).all()
        )
        if analysis_ids.union(plan_ids) != set(request.artifact_ids):
            raise YouTubePermissionError("One or more delegated artifacts are outside this workspace or do not exist.")
    membership_agent_ids = set(
        db.scalars(select(TeamAgent.agent_id).where(TeamAgent.team_id == team.id)).all()
    )
    coordinator = db.get(Agent, team.coordinator_agent_id) if team.coordinator_agent_id else None
    if coordinator is None or coordinator.id not in membership_agent_ids:
        coordinator = db.scalar(
            select(Agent).where(
                Agent.workspace_id == context.workspace.id,
                Agent.slug == "atlas",
                Agent.id.in_(membership_agent_ids),
            )
        )
    if coordinator is None:
        raise YouTubeTeamUnavailableError("The YouTube Growth team has no configured Coordinator.")
    role_agents: dict[str, Agent] = {}
    for role, slug in DELEGATE_ROLES[request.action]:
        agent = db.scalar(
            select(Agent).where(
                Agent.workspace_id == context.workspace.id,
                Agent.slug == slug,
                Agent.id.in_(membership_agent_ids),
            )
        )
        if agent is None:
            raise YouTubeTeamUnavailableError(f"The YouTube Growth team is missing its {role} agent.")
        role_agents[role] = agent
    coordinator_task = Task(
        workspace_id=context.workspace.id,
        team_id=team.id,
        assigned_agent_id=coordinator.id,
        title=f"YouTube Growth: {request.action.replace('_', ' ')}",
        description="Coordinator task created through the authenticated Teamora backend.",
        status="queued",
        priority="normal",
        progress=0,
        input_json={
            "source": "youtube_growth_delegate",
            "action": request.action,
            "input": request.input,
            "artifactIds": request.artifact_ids,
            "idempotencyKey": request.idempotency_key,
            "owner": "Atlas",
        },
        created_by=user.id,
    )
    db.add(coordinator_task)
    db.flush()
    children: list[Task] = []
    for role, _slug in DELEGATE_ROLES[request.action]:
        child = Task(
            workspace_id=context.workspace.id,
            team_id=team.id,
            assigned_agent_id=role_agents[role].id,
            parent_task_id=coordinator_task.id,
            title=f"{role}: {request.action.replace('_', ' ')}",
            description=f"Specialist role: {role}",
            status="queued",
            priority="normal",
            progress=0,
            input_json={
                "source": "youtube_growth_delegate",
                "role": role,
                "action": request.action,
                "input": request.input,
                "artifactIds": request.artifact_ids,
            },
            created_by=user.id,
        )
        db.add(child)
        children.append(child)
    db.commit()
    db.refresh(coordinator_task)
    for child in children:
        db.refresh(child)
    return _delegated_task_response(db, coordinator_task)
