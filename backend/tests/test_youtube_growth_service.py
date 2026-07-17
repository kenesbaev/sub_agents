from __future__ import annotations

import json
import sys
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import Settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models import (  # noqa: E402
    Agent,
    IntegrationAccount,
    IntegrationProvider,
    IntegrationToken,
    UserIntegration,
    Task,
    User,
    Workspace,
    WorkspaceMember,
    YouTubeAnalysisRun,
    YouTubeContentPlan,
    YouTubeContentPlanItem,
)
from app.youtube_growth.errors import (  # noqa: E402
    AnalyticsUnavailableError,
    CommentsDisabledError,
    IdempotencyConflictError,
    ModelUnavailableError,
    YouTubePermissionError,
    YouTubeQuotaError,
    OperationInProgressError,
)
from app.youtube_growth.router import _raise_domain_error  # noqa: E402
from app.youtube_growth.schemas import (  # noqa: E402
    ChannelAnalysisRequest,
    CompetitorAnalysisRequest,
    ContentPlanCreateRequest,
    DelegateRequest,
    GrowthSnapshotCreateRequest,
    VideoAnalysisRequest,
)
from app.youtube_growth.service import (  # noqa: E402
    YouTubeCredentials,
    analyze_channel,
    analyze_competitors,
    analyze_video,
    create_content_plan,
    create_growth_snapshot,
    delegate_to_youtube_team,
    list_youtube_account_statuses,
    load_youtube_credentials,
)
from app.token_crypto import encrypt_token  # noqa: E402


def video_payload(
    video_id: str = "video01",
    *,
    channel_id: str = "UCownerChannel01",
    views: int = 0,
    captions: bool = False,
) -> dict:
    return {
        "id": video_id,
        "snippet": {
            "channelId": channel_id,
            "channelTitle": "Channel",
            "title": f"Video {video_id}",
            "description": "Description supplied by YouTube.",
            "publishedAt": "2026-07-01T12:00:00Z",
            "tags": ["workflow"],
            "thumbnails": {"high": {"url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"}},
        },
        "statistics": {
            "viewCount": str(views),
            "likeCount": "0",
            "commentCount": "0",
        },
        "contentDetails": {"duration": "PT5M", "caption": "true" if captions else "false"},
        "status": {"privacyStatus": "public"},
    }


def channel_payload(*, hidden_subscribers: bool = False) -> dict:
    statistics = {"viewCount": "1000", "videoCount": "12", "hiddenSubscriberCount": hidden_subscribers}
    if not hidden_subscribers:
        statistics["subscriberCount"] = "100"
    return {
        "id": "UCchannelExample01",
        "snippet": {
            "title": "Example Channel",
            "description": "Channel description",
            "publishedAt": "2025-01-01T00:00:00Z",
        },
        "statistics": statistics,
        "contentDetails": {"relatedPlaylists": {"uploads": "UUchannelExample01"}},
    }


def plan_json(days: int) -> str:
    items = []
    for index in range(days):
        topic = f"Topic {index + 1}"
        items.append(
            {
                "item": {
                    "publish_date": (date.today() + timedelta(days=index + 1)).isoformat(),
                    "content_pillar": "automation",
                    "target_audience": "business owners",
                    "topic": topic,
                    "why_now": "It matches the current planning brief.",
                    "format": "long_video",
                    "goal": "awareness",
                    "estimated_duration": "8 minutes",
                    "titles": [f"{topic} A", f"{topic} B", f"{topic} C"],
                    "hooks": ["Hook A", "Hook B", "Hook C"],
                    "thumbnail_briefs": ["Brief A", "Brief B"],
                    "script_outline": ["Hook", "Evidence", "Demo", "CTA"],
                    "cta": "Subscribe for the next analysis.",
                    "description_draft": "Draft description.",
                    "chapters": ["00:00 Hook"],
                    "shorts_ideas": ["One short excerpt"],
                    "facts_to_verify": ["Verify the case-study outcome."],
                    "sources": [],
                    "primary_kpi": "average view duration versus channel baseline",
                    "opportunity_score": 0,
                    "confidence": "medium",
                    "score_explanation": "Backend-calculated score replaces this value.",
                },
                "score_components": {
                    "topic_demand": {"score": 80, "explanation": "Demand estimate from supplied context."},
                    "competition_gap": {"score": 60, "explanation": "Gap estimate from supplied context."},
                    "hook_strength": {"score": 70, "explanation": "Hook is concrete and audience-specific."},
                    "title_thumbnail_packaging": {"score": 90, "explanation": "Packaging has one clear promise."},
                    "channel_fit": {"score": 50, "explanation": "Neutral without owned-channel history."},
                    "timing_relevance": {"score": 75, "explanation": "Timing matches the requested window."},
                },
            }
        )
    return json.dumps({"items": items})


class StaticPlanModel:
    def __init__(self, days: int) -> None:
        self.days = days
        self.calls = 0

    async def generate(self, prompt: str) -> str:
        self.calls += 1
        return plan_json(self.days)


class YouTubeGrowthServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        self.user = User(email="owner@example.com")
        self.db.add(self.user)
        self.db.flush()
        self.workspace = Workspace(name="Owner Workspace", slug="owner-workspace", owner_id=self.user.id)
        self.db.add(self.workspace)
        self.db.flush()
        self.db.add(WorkspaceMember(workspace_id=self.workspace.id, user_id=self.user.id, role="owner"))
        self.db.commit()
        self.settings = Settings(
            database_url="sqlite+pysqlite:///:memory:",
            youtube_api_key="test-api-key",
            youtube_llm_api_url="",
            youtube_llm_api_key="",
            youtube_llm_model="",
        )

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    async def test_video_analysis_keeps_comments_and_captions_failures_partial(self) -> None:
        fake_client = SimpleNamespace(
            get_video=AsyncMock(return_value=video_payload(views=0)),
            comments=AsyncMock(side_effect=CommentsDisabledError()),
        )
        request = VideoAnalysisRequest(url="https://www.youtube.com/watch?v=video01")
        with patch("app.youtube_growth.service.YouTubeClient", return_value=fake_client):
            result = await analyze_video(self.db, self.settings, self.user, self.workspace.id, request)

        self.assertEqual("partial", result.status)
        self.assertTrue(result.partial)
        self.assertEqual(0, result.metrics["views"])
        self.assertTrue(any("Comments are disabled" in item for item in result.limitations))
        self.assertTrue(any("metadata only" in item for item in result.limitations))
        self.assertEqual("metadata_and_available_comments", result.facts["analysis_basis"])
        self.assertEqual("https://www.youtube.com/watch?v=video01", result.sources[0].url)

    async def test_missing_statistics_remain_unavailable_instead_of_becoming_zero(self) -> None:
        payload = video_payload()
        payload["statistics"] = {}
        fake_client = SimpleNamespace(get_video=AsyncMock(return_value=payload))
        request = VideoAnalysisRequest(
            url="https://www.youtube.com/watch?v=video01",
            include_comments=False,
            include_captions=False,
        )
        with patch("app.youtube_growth.service.YouTubeClient", return_value=fake_client):
            result = await analyze_video(self.db, self.settings, self.user, self.workspace.id, request)
        self.assertIsNone(result.metrics["views"])
        self.assertIsNone(result.metrics["likes"])
        self.assertIsNone(result.metrics["comments"])

    async def test_comment_analysis_returns_bounded_positive_negative_and_recurring_signals(self) -> None:
        def comment(text: str) -> dict:
            return {
                "snippet": {
                    "topLevelComment": {
                        "snippet": {"textDisplay": text, "likeCount": "1", "publishedAt": "2026-07-01T00:00:00Z"}
                    },
                    "totalReplyCount": "0",
                }
            }

        fake_client = SimpleNamespace(
            get_video=AsyncMock(return_value=video_payload()),
            comments=AsyncMock(
                return_value=[
                    comment("Great and useful automation walkthrough?"),
                    comment("This automation is bad and confusing?"),
                ]
            ),
        )
        request = VideoAnalysisRequest(
            url="https://www.youtube.com/watch?v=video01",
            include_comments=True,
            include_captions=False,
        )
        with patch("app.youtube_growth.service.YouTubeClient", return_value=fake_client):
            result = await analyze_video(self.db, self.settings, self.user, self.workspace.id, request)
        signals = result.insights["comment_signals"]
        self.assertEqual(1, signals["positive_lexical_matches"])
        self.assertEqual(1, signals["negative_lexical_matches"])
        self.assertEqual(2, signals["questions"])
        self.assertIn("automation", [item["term"] for item in signals["repeated_terms"]])
        self.assertIn("not a definitive sentiment model", signals["method_limit"])

    async def test_explicit_owned_account_analysis_forces_oauth_lookup(self) -> None:
        credentials = YouTubeCredentials(
            account_id=9,
            channel_id="UCownerChannel01",
            access_token="owner-token",
            scopes=frozenset({"https://www.googleapis.com/auth/youtube.readonly"}),
            label="Owner channel",
        )
        fake_client = SimpleNamespace(get_video=AsyncMock(return_value=video_payload()))
        request = VideoAnalysisRequest(
            account_id=9,
            url="https://www.youtube.com/watch?v=video01",
            include_comments=False,
            include_captions=False,
        )
        with (
            patch("app.youtube_growth.service.load_youtube_credentials", return_value=credentials),
            patch("app.youtube_growth.service.YouTubeClient", return_value=fake_client),
        ):
            await analyze_video(self.db, self.settings, self.user, self.workspace.id, request)
        fake_client.get_video.assert_awaited_once_with("video01", require_oauth=True)

    async def test_owned_caption_analysis_exposes_bounded_timestamped_sources(self) -> None:
        credentials = YouTubeCredentials(
            account_id=9,
            channel_id="UCownerChannel01",
            access_token="owner-token",
            scopes=frozenset({"https://www.googleapis.com/auth/youtube.readonly"}),
            label="Owner channel",
        )
        caption_blocks = []
        for index in range(25):
            caption_blocks.append(
                f"{index + 1}\n00:00:{index:02d},000 --> 00:00:{index:02d},900\nCaption segment {index}\n"
            )
        fake_client = SimpleNamespace(
            get_video=AsyncMock(return_value=video_payload(captions=True)),
            comments=AsyncMock(return_value=[]),
            captions=AsyncMock(return_value=[{"id": "caption-track", "snippet": {"language": "en"}}]),
            download_caption=AsyncMock(return_value="\n".join(caption_blocks)),
        )
        request = VideoAnalysisRequest(
            account_id=9,
            url="https://www.youtube.com/watch?v=video01",
            language="en",
            include_comments=False,
            include_captions=True,
        )
        with (
            patch("app.youtube_growth.service.load_youtube_credentials", return_value=credentials),
            patch("app.youtube_growth.service.YouTubeClient", return_value=fake_client),
        ):
            result = await analyze_video(self.db, self.settings, self.user, self.workspace.id, request)

        caption_sources = [source for source in result.sources if source.source_type == "authorized_youtube_caption"]
        self.assertEqual(20, len(caption_sources))
        self.assertEqual(0, caption_sources[0].timestamp_seconds)
        self.assertEqual(24, caption_sources[-1].timestamp_seconds)
        self.assertEqual("https://www.youtube.com/watch?v=video01&t=24s", caption_sources[-1].url)
        self.assertIn("Authorized caption segment", caption_sources[-1].fact)

    async def test_channel_with_hidden_subscribers_has_no_invented_ratio(self) -> None:
        fake_client = SimpleNamespace(
            resolve_channel=AsyncMock(return_value=channel_payload(hidden_subscribers=True)),
            channel_videos=AsyncMock(return_value=[video_payload(views=25)]),
        )
        request = ChannelAnalysisRequest(url="@example", max_videos=1)
        with patch("app.youtube_growth.service.YouTubeClient", return_value=fake_client):
            result = await analyze_channel(self.db, self.settings, self.user, self.workspace.id, request)

        self.assertTrue(result.partial)
        self.assertTrue(any("hides its subscriber count" in item for item in result.limitations))
        self.assertIsNone(result.facts["videos"][0]["views_to_subscribers_ratio"])

    async def test_competitor_analysis_combines_regional_trends_and_sample_relative_signals(self) -> None:
        searched = []
        for index in range(10):
            video = video_payload(f"search{index:02d}", views=1000 if index == 0 else 100)
            video["snippet"]["title"] = (
                "Quantumgap AI automation secret" if index == 0 else f"AI automation workflow {index}"
            )
            video["snippet"]["description"] = "Subscribe and comment after trying this workflow."
            searched.append(video)
        trend = video_payload("trend001", views=500)
        trend["snippet"]["title"] = "AI automation trend"
        fake_client = SimpleNamespace(
            search_videos=AsyncMock(return_value=searched),
            trending_videos=AsyncMock(return_value=[trend]),
            get_channels=AsyncMock(return_value=[channel_payload()]),
        )
        request = CompetitorAnalysisRequest(query="AI automation", language="en", region="US", limit=10)
        with patch("app.youtube_growth.service.YouTubeClient", return_value=fake_client):
            result = await analyze_competitors(self.db, self.settings, self.user, self.workspace.id, request)

        fake_client.trending_videos.assert_awaited_once_with("US", 10)
        self.assertIn("trend001", result.insights["regional_trending_match_ids"])
        self.assertIn("automation", [item["term"] for item in result.insights["repeated_topics"]])
        self.assertIn("quantumgap", [item["term"] for item in result.insights["content_gaps"]])
        self.assertTrue(result.insights["description_cta_signals"])
        packaging = result.score_components.components.title_thumbnail_packaging
        self.assertIn("not visually inspected", packaging.explanation)

    async def test_content_plans_for_seven_and_thirty_days_are_persisted_after_validation(self) -> None:
        for days in (7, 30):
            with self.subTest(days=days):
                request = ContentPlanCreateRequest(
                    days=days,
                    niche="AI automation",
                    language="en",
                    region="US",
                    goal="awareness",
                    publishing_frequency="daily",
                    content_pillars=["automation"],
                    idempotency_key=f"plan-{days}-unique",
                )
                response = await create_content_plan(
                    self.db,
                    self.settings,
                    self.user,
                    self.workspace.id,
                    request,
                    model_client=StaticPlanModel(days),
                )
                self.assertEqual(days, len(response.items))
                self.assertEqual(days, len(response.score_breakdowns))
                self.assertTrue(all(component.explanation for component in response.score_breakdowns))
                records = self.db.scalars(
                    select(YouTubeContentPlanItem).where(YouTubeContentPlanItem.plan_id == response.id)
                ).all()
                self.assertEqual(days, len(records))
                self.assertEqual("Verify the case-study outcome.", response.items[0].facts_to_verify[0])

    async def test_missing_llm_configuration_is_a_clear_503_and_failed_artifact(self) -> None:
        request = ContentPlanCreateRequest(
            days=7,
            niche="AI automation",
            language="en",
            region="US",
            goal="awareness",
            publishing_frequency="daily",
            content_pillars=["automation"],
        )
        with self.assertRaises(ModelUnavailableError) as raised:
            await create_content_plan(self.db, self.settings, self.user, self.workspace.id, request)
        self.assertEqual(503, raised.exception.status_code)
        plan = self.db.scalar(select(YouTubeContentPlan).order_by(YouTubeContentPlan.id.desc()))
        self.assertEqual("failed", plan.status)

    async def test_running_plan_idempotency_key_returns_409_instead_of_duplicate_insert(self) -> None:
        existing = YouTubeContentPlan(
            workspace_id=self.workspace.id,
            created_by=self.user.id,
            horizon_days=7,
            niche="AI automation",
            language="en",
            region="US",
            goal="awareness",
            status="running",
            request_json={},
            idempotency_key="running-plan-key",
        )
        self.db.add(existing)
        self.db.commit()
        request = ContentPlanCreateRequest(
            days=7,
            niche="AI automation",
            language="en",
            region="US",
            goal="awareness",
            publishing_frequency="daily",
            content_pillars=["automation"],
            idempotency_key="running-plan-key",
        )
        with self.assertRaises(OperationInProgressError) as raised:
            await create_content_plan(
                self.db,
                self.settings,
                self.user,
                self.workspace.id,
                request,
                model_client=StaticPlanModel(7),
            )
        self.assertEqual(409, raised.exception.status_code)

    async def test_foreign_account_id_is_fail_closed_and_scope_strings_are_not_exposed(self) -> None:
        provider = IntegrationProvider(key="youtube", name="YouTube", auth_type="oauth2")
        other_user = User(email="channel-owner@example.com")
        self.db.add_all([provider, other_user])
        self.db.flush()
        foreign_integration = UserIntegration(
            user_id=other_user.id,
            provider_id=provider.id,
            status="connected",
        )
        own_integration = UserIntegration(
            user_id=self.user.id,
            provider_id=provider.id,
            status="connected",
        )
        self.db.add_all([foreign_integration, own_integration])
        self.db.flush()
        foreign_account = IntegrationAccount(
            user_integration_id=foreign_integration.id,
            provider_id=provider.id,
            account_identifier="UCforeignChannel01",
            account_label="Foreign",
        )
        own_account = IntegrationAccount(
            user_integration_id=own_integration.id,
            provider_id=provider.id,
            account_identifier="UCownerChannel01",
            account_label="Owner",
        )
        self.db.add_all([foreign_account, own_account])
        self.db.flush()
        self.db.add(
            IntegrationToken(
                user_integration_id=own_integration.id,
                integration_account_id=own_account.id,
                encrypted_access_token=encrypt_token("access-token"),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                scopes=(
                    "https://www.googleapis.com/auth/youtube.readonly "
                    "https://www.googleapis.com/auth/yt-analytics.readonly"
                ),
            )
        )
        self.db.commit()

        with self.assertRaises(YouTubePermissionError):
            load_youtube_credentials(self.db, self.user, account_id=foreign_account.id, required=False)
        statuses = list_youtube_account_statuses(self.db, self.user)
        self.assertEqual(1, len(statuses))
        self.assertTrue(statuses[0].can_analyze_private_metrics)
        self.assertNotIn("granted_scopes", statuses[0].model_dump())
        token = self.db.scalar(
            select(IntegrationToken).where(IntegrationToken.integration_account_id == own_account.id)
        )
        token.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        self.db.commit()
        expired_status = list_youtube_account_statuses(self.db, self.user)[0]
        self.assertFalse(expired_status.connected)
        self.assertFalse(expired_status.can_read)
        self.assertFalse(expired_status.can_analyze_private_metrics)

    async def test_analysis_from_another_workspace_cannot_seed_a_plan(self) -> None:
        other_user = User(email="other@example.com")
        self.db.add(other_user)
        self.db.flush()
        other_workspace = Workspace(name="Other", slug="other-workspace", owner_id=other_user.id)
        self.db.add(other_workspace)
        self.db.flush()
        self.db.add(WorkspaceMember(workspace_id=other_workspace.id, user_id=other_user.id, role="owner"))
        analysis = YouTubeAnalysisRun(
            workspace_id=other_workspace.id,
            created_by=other_user.id,
            kind="video",
            status="completed",
            request_json={},
            result_json={},
        )
        self.db.add(analysis)
        self.db.commit()
        request = ContentPlanCreateRequest(
            analysis_ids=[analysis.id],
            days=7,
            niche="AI automation",
            language="en",
            region="US",
            goal="awareness",
            publishing_frequency="daily",
            content_pillars=["automation"],
        )
        with self.assertRaises(YouTubePermissionError):
            await create_content_plan(
                self.db,
                self.settings,
                self.user,
                self.workspace.id,
                request,
                model_client=StaticPlanModel(7),
            )

    async def test_growth_snapshot_requires_actual_analytics_scope(self) -> None:
        credentials = YouTubeCredentials(
            account_id=9,
            channel_id="UCownerChannel01",
            access_token="encrypted-at-rest-only",
            scopes=frozenset({"https://www.googleapis.com/auth/youtube.readonly"}),
            label="Owner channel",
        )
        request = GrowthSnapshotCreateRequest(account_id=9, video_id="video01", checkpoint="24h")
        with patch("app.youtube_growth.service.load_youtube_credentials", return_value=credentials):
            with self.assertRaises(YouTubePermissionError):
                await create_growth_snapshot(self.db, self.settings, self.user, self.workspace.id, request)

    async def test_future_checkpoint_remains_queued_without_cumulative_analytics_call(self) -> None:
        credentials = YouTubeCredentials(
            account_id=9,
            channel_id="UCownerChannel01",
            access_token="oauth-access-token",
            scopes=frozenset(
                {
                    "https://www.googleapis.com/auth/youtube.readonly",
                    "https://www.googleapis.com/auth/yt-analytics.readonly",
                }
            ),
            label="Owner channel",
        )
        payload = video_payload(views=1)
        payload["snippet"]["publishedAt"] = datetime.now(UTC).isoformat()
        fake_client = SimpleNamespace(
            get_video=AsyncMock(return_value=payload),
            analytics_report=AsyncMock(),
        )
        request = GrowthSnapshotCreateRequest(account_id=9, video_id="video01", checkpoint="7d")
        with (
            patch("app.youtube_growth.service.load_youtube_credentials", return_value=credentials),
            patch("app.youtube_growth.service.YouTubeClient", return_value=fake_client),
        ):
            result = await create_growth_snapshot(self.db, self.settings, self.user, self.workspace.id, request)

        self.assertEqual("queued", result.status)
        self.assertGreater(result.scheduled_for, datetime.now(UTC))
        self.assertIsNone(result.observed_at)
        self.assertEqual([], result.recommendations)
        self.assertEqual("https://www.youtube.com/watch?v=video01", result.sources[0].url)
        fake_client.analytics_report.assert_not_awaited()

    async def test_unavailable_packaging_metrics_yield_partial_snapshot_not_fake_values(self) -> None:
        credentials = YouTubeCredentials(
            account_id=9,
            channel_id="UCownerChannel01",
            access_token="oauth-access-token",
            scopes=frozenset(
                {
                    "https://www.googleapis.com/auth/youtube.readonly",
                    "https://www.googleapis.com/auth/yt-analytics.readonly",
                }
            ),
            label="Owner channel",
        )

        async def analytics_report(**kwargs):
            metrics = kwargs["metrics"]
            dimensions = kwargs.get("dimensions")
            video_id = kwargs.get("video_id")
            if metrics == ["videoThumbnailImpressions", "videoThumbnailImpressionsClickRate"]:
                raise AnalyticsUnavailableError()
            if metrics == ["averageViewPercentage"] or dimensions:
                return []
            if video_id == "older01":
                return [{"views": 80, "estimatedMinutesWatched": 180, "averageViewDuration": 110}]
            if video_id == "older02":
                return [{"views": 120, "estimatedMinutesWatched": 220, "averageViewDuration": 130}]
            return [{"views": 100, "estimatedMinutesWatched": 200, "averageViewDuration": 120}]

        fake_client = SimpleNamespace(
            get_video=AsyncMock(return_value=video_payload(views=100)),
            resolve_channel=AsyncMock(return_value=channel_payload()),
            channel_videos=AsyncMock(
                return_value=[
                    video_payload("older01", views=80),
                    video_payload("older02", views=120),
                ]
            ),
            analytics_report=AsyncMock(side_effect=analytics_report),
        )
        request = GrowthSnapshotCreateRequest(account_id=9, video_id="video01", checkpoint="24h")
        with (
            patch("app.youtube_growth.service.load_youtube_credentials", return_value=credentials),
            patch("app.youtube_growth.service.YouTubeClient", return_value=fake_client),
        ):
            result = await create_growth_snapshot(self.db, self.settings, self.user, self.workspace.id, request)

        self.assertEqual("partial", result.status)
        self.assertNotIn("videoThumbnailImpressionsClickRate", result.metrics)
        self.assertTrue(any("CTR are unavailable" in item for item in result.limitations))
        self.assertEqual(2, result.baseline["sample_size"])
        self.assertEqual("https://www.youtube.com/watch?v=video01", result.sources[0].url)

    async def test_growth_snapshot_collects_bounded_official_analytics_facets(self) -> None:
        credentials = YouTubeCredentials(
            account_id=9,
            channel_id="UCownerChannel01",
            access_token="oauth-access-token",
            scopes=frozenset(
                {
                    "https://www.googleapis.com/auth/youtube.readonly",
                    "https://www.googleapis.com/auth/yt-analytics.readonly",
                }
            ),
            label="Owner channel",
        )

        async def analytics_report(**kwargs):
            metrics = kwargs["metrics"]
            dimensions = kwargs.get("dimensions")
            video_id = kwargs.get("video_id")
            if metrics == ["videoThumbnailImpressions", "videoThumbnailImpressionsClickRate"]:
                return [{"videoThumbnailImpressions": 500, "videoThumbnailImpressionsClickRate": 4.2}]
            if metrics == ["averageViewPercentage"]:
                return [{"averageViewPercentage": 63.5}]
            if dimensions == ["insightTrafficSourceType"]:
                return [
                    {"insightTrafficSourceType": "RELATED_VIDEO", "views": 20},
                    {
                        "insightTrafficSourceType": "YT_SEARCH",
                        "views": 80,
                        "estimatedMinutesWatched": 140,
                    },
                ]
            if dimensions == ["country"]:
                return [
                    {"country": "CA", "views": 10},
                    {"country": "US", "views": 90, "estimatedMinutesWatched": 170},
                    *[
                        {"country": f"TEST-{index}", "views": index, "estimatedMinutesWatched": index * 2}
                        for index in range(1, 26)
                    ],
                ]
            if dimensions == ["deviceType"]:
                return [{"deviceType": "MOBILE", "views": 75, "estimatedMinutesWatched": 120}]
            if dimensions == ["subscribedStatus"]:
                return [
                    {
                        "subscribedStatus": "SUBSCRIBED",
                        "views": 35,
                        "estimatedMinutesWatched": 80,
                        "averageViewDuration": 137,
                        "averageViewPercentage": 70.1,
                    },
                    {
                        "subscribedStatus": "UNSUBSCRIBED",
                        "views": 65,
                        "estimatedMinutesWatched": 120,
                        "averageViewDuration": 111,
                        "averageViewPercentage": 55.4,
                    },
                ]
            if video_id == "older01":
                return [
                    {
                        "views": 85,
                        "estimatedMinutesWatched": 170,
                        "averageViewDuration": 108,
                        "averageViewPercentage": 52.0,
                    }
                ]
            return [{"views": 100, "estimatedMinutesWatched": 200, "averageViewDuration": 120}]

        owned_channel = channel_payload()
        owned_channel["id"] = credentials.channel_id
        fake_client = SimpleNamespace(
            get_video=AsyncMock(return_value=video_payload(views=100)),
            resolve_channel=AsyncMock(return_value=owned_channel),
            channel_videos=AsyncMock(return_value=[video_payload("older01", views=85)]),
            analytics_report=AsyncMock(side_effect=analytics_report),
        )
        request = GrowthSnapshotCreateRequest(
            account_id=credentials.account_id,
            video_id="video01",
            checkpoint="24h",
            baseline_video_count=5,
        )
        with (
            patch("app.youtube_growth.service.load_youtube_credentials", return_value=credentials),
            patch("app.youtube_growth.service.YouTubeClient", return_value=fake_client),
        ):
            result = await create_growth_snapshot(self.db, self.settings, self.user, self.workspace.id, request)

        self.assertEqual(63.5, result.metrics["averageViewPercentage"])
        self.assertEqual("YT_SEARCH", result.metrics["traffic_sources"][0]["insightTrafficSourceType"])
        self.assertEqual("US", result.metrics["geography"][0]["country"])
        self.assertEqual(25, len(result.metrics["geography"]))
        canada = next(row for row in result.metrics["geography"] if row["country"] == "CA")
        self.assertNotIn("estimatedMinutesWatched", canada)
        self.assertEqual("MOBILE", result.metrics["devices"][0]["deviceType"])
        self.assertEqual(2, len(result.metrics["audience_by_subscription"]))
        self.assertEqual(credentials.channel_id, result.metrics["channel_context"]["channel_id"])
        self.assertIsNone(result.metrics["returning_viewers"]["value"])
        self.assertFalse(result.metrics["returning_viewers"]["available"])
        self.assertEqual(52.0, result.baseline["averageViewPercentage"])
        self.assertTrue(any("Returning viewers" in item for item in result.limitations))
        requested_metrics = [call.kwargs["metrics"] for call in fake_client.analytics_report.await_args_list]
        self.assertFalse(any("returningViewers" in metrics for metrics in requested_metrics))

    async def test_unsupported_analytics_facets_are_limitations_without_fake_zeroes(self) -> None:
        credentials = YouTubeCredentials(
            account_id=9,
            channel_id="UCownerChannel01",
            access_token="oauth-access-token",
            scopes=frozenset(
                {
                    "https://www.googleapis.com/auth/youtube.readonly",
                    "https://www.googleapis.com/auth/yt-analytics.readonly",
                }
            ),
            label="Owner channel",
        )

        async def analytics_report(**kwargs):
            if kwargs["metrics"] == [
                "views",
                "estimatedMinutesWatched",
                "averageViewDuration",
                "likes",
                "comments",
                "subscribersGained",
                "subscribersLost",
            ]:
                return [{"views": 0}]
            if kwargs["metrics"] == ["videoThumbnailImpressions", "videoThumbnailImpressionsClickRate"]:
                return []
            raise AnalyticsUnavailableError()

        hidden_channel = channel_payload(hidden_subscribers=True)
        hidden_channel["id"] = credentials.channel_id
        fake_client = SimpleNamespace(
            get_video=AsyncMock(return_value=video_payload(views=0)),
            resolve_channel=AsyncMock(return_value=hidden_channel),
            channel_videos=AsyncMock(return_value=[]),
            analytics_report=AsyncMock(side_effect=analytics_report),
        )
        request = GrowthSnapshotCreateRequest(account_id=9, video_id="video01", checkpoint="24h")
        with (
            patch("app.youtube_growth.service.load_youtube_credentials", return_value=credentials),
            patch("app.youtube_growth.service.YouTubeClient", return_value=fake_client),
        ):
            result = await create_growth_snapshot(self.db, self.settings, self.user, self.workspace.id, request)

        self.assertEqual(0, result.metrics["views"])
        self.assertNotIn("averageViewPercentage", result.metrics)
        self.assertNotIn("traffic_sources", result.metrics)
        self.assertNotIn("geography", result.metrics)
        self.assertNotIn("devices", result.metrics)
        self.assertNotIn("audience_by_subscription", result.metrics)
        self.assertIsNone(result.metrics["channel_context"]["subscriber_count"])
        self.assertFalse(result.metrics["returning_viewers"]["available"])
        self.assertTrue(any("Average view percentage is unavailable" in item for item in result.limitations))
        self.assertTrue(any("traffic sources are unavailable" in item for item in result.limitations))
        self.assertTrue(any("Subscribed/unsubscribed" in item for item in result.limitations))

    async def test_domain_error_payload_is_stable_for_frontend_states(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            _raise_domain_error(YouTubeQuotaError())
        self.assertEqual(429, raised.exception.status_code)
        self.assertEqual(
            {"code": "quota_exceeded", "message": "YouTube API quota was exceeded. Try again after the quota resets.", "retryable": True},
            raised.exception.detail,
        )

    async def test_delegate_creates_coordinator_and_role_tasks_without_publishing(self) -> None:
        atlas = Agent(
            workspace_id=self.workspace.id,
            slug="atlas",
            name="Atlas",
            role="Coordinator",
            status="ready",
        )
        self.db.add(atlas)
        artifact = YouTubeAnalysisRun(
            workspace_id=self.workspace.id,
            created_by=self.user.id,
            kind="competitors",
            status="completed",
            request_json={},
            result_json={},
        )
        self.db.add(artifact)
        self.db.commit()
        response = delegate_to_youtube_team(
            self.db,
            self.user,
            DelegateRequest(
                workspace_id=self.workspace.id,
                action="analyze_competitors",
                input={"query": "AI workflows"},
                artifact_ids=[artifact.id],
            ),
        )
        self.assertEqual(["Trend Scout", "Competitor Analyst"], [item.role for item in response.child_tasks])
        coordinator = self.db.get(Task, response.coordinator_task_id)
        self.assertEqual(atlas.id, coordinator.assigned_agent_id)
        self.assertEqual("queued", coordinator.status)
        self.assertNotIn("publish", coordinator.input_json["action"])
        children = self.db.scalars(select(Task).where(Task.parent_task_id == coordinator.id)).all()
        self.assertTrue(all(child.team_id == coordinator.team_id for child in children))
        self.assertTrue(all(child.assigned_agent_id is not None for child in children))

    async def test_delegate_rejects_foreign_workspace_artifact(self) -> None:
        other_user = User(email="delegate-other@example.com")
        self.db.add(other_user)
        self.db.flush()
        other_workspace = Workspace(name="Delegate Other", slug="delegate-other", owner_id=other_user.id)
        self.db.add(other_workspace)
        self.db.flush()
        artifact = YouTubeAnalysisRun(
            workspace_id=other_workspace.id,
            created_by=other_user.id,
            kind="video",
            status="completed",
            request_json={},
            result_json={},
        )
        self.db.add(artifact)
        self.db.commit()
        with self.assertRaises(YouTubePermissionError):
            delegate_to_youtube_team(
                self.db,
                self.user,
                DelegateRequest(
                    workspace_id=self.workspace.id,
                    action="analyze_video",
                    artifact_ids=[artifact.id],
                ),
            )

    async def test_delegate_idempotency_returns_existing_user_scoped_task_tree(self) -> None:
        request = DelegateRequest(
            workspace_id=self.workspace.id,
            idempotency_key="delegate-video-001",
            action="analyze_video",
            input={"url": "https://www.youtube.com/watch?v=video01"},
        )
        first = delegate_to_youtube_team(self.db, self.user, request)
        second = delegate_to_youtube_team(self.db, self.user, request)

        self.assertEqual(first.coordinator_task_id, second.coordinator_task_id)
        self.assertEqual([item.id for item in first.child_tasks], [item.id for item in second.child_tasks])
        coordinator_count = len(
            self.db.scalars(
                select(Task).where(
                    Task.workspace_id == self.workspace.id,
                    Task.created_by == self.user.id,
                    Task.parent_task_id.is_(None),
                )
            ).all()
        )
        self.assertEqual(1, coordinator_count)

        with self.assertRaises(IdempotencyConflictError):
            delegate_to_youtube_team(
                self.db,
                self.user,
                request.model_copy(update={"input": {"url": "https://www.youtube.com/watch?v=other01"}}),
            )

        collaborator = User(email="delegate-collaborator@example.com")
        self.db.add(collaborator)
        self.db.flush()
        self.db.add(WorkspaceMember(workspace_id=self.workspace.id, user_id=collaborator.id, role="member"))
        self.db.commit()
        collaborator_response = delegate_to_youtube_team(self.db, collaborator, request)
        self.assertNotEqual(first.coordinator_task_id, collaborator_response.coordinator_task_id)


if __name__ == "__main__":
    unittest.main()
