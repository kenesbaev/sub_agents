from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.models import User, Workspace, WorkspaceMember, YouTubeContentPlan, YouTubeContentPlanItem  # noqa: E402
from app.security import get_current_user  # noqa: E402
from app.youtube_growth.router import router  # noqa: E402
from app.youtube_growth.schemas import (  # noqa: E402
    ContentPlanItem,
    GrowthScoreComponents,
    ScoreComponent,
)
from app.youtube_growth.scoring import calculate_growth_opportunity_score  # noqa: E402


def score_components(score: int = 60) -> GrowthScoreComponents:
    def component(label: str) -> ScoreComponent:
        return ScoreComponent(score=score, explanation=f"Validated {label} evidence.")

    return GrowthScoreComponents(
        topic_demand=component("demand"),
        competition_gap=component("competition gap"),
        hook_strength=component("hook"),
        title_thumbnail_packaging=component("packaging"),
        channel_fit=component("channel fit"),
        timing_relevance=component("timing"),
    )


def item_payload(topic: str = "Original topic") -> ContentPlanItem:
    return ContentPlanItem(
        publish_date=date(2026, 8, 1),
        content_pillar="AI automation",
        target_audience="Small business owners",
        topic=topic,
        why_now="The selected research shows current audience demand.",
        format="long_video",
        goal="awareness",
        estimated_duration="8 minutes",
        titles=["Title A", "Title B", "Title C"],
        hooks=["Hook A", "Hook B", "Hook C"],
        thumbnail_briefs=["Brief A", "Brief B"],
        script_outline=["Hook", "Evidence", "Demo", "CTA"],
        cta="Subscribe for the next analysis.",
        description_draft="A source-backed draft description.",
        chapters=["00:00 Hook"],
        shorts_ideas=["A concise demo excerpt"],
        facts_to_verify=["Verify the cited benchmark"],
        sources=["https://www.youtube.com/watch?v=source01"],
        primary_kpi="Average view duration versus channel baseline",
        opportunity_score=60,
        confidence="medium",
        score_explanation="Initial validated weighted score.",
    )


class YouTubeGrowthPlanItemApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        with self.session_factory() as db:
            owner = User(email="plan-owner@example.com")
            db.add(owner)
            db.flush()
            workspace = Workspace(name="Plan Workspace", slug="plan-workspace", owner_id=owner.id)
            db.add(workspace)
            db.flush()
            db.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role="owner"))
            plan = YouTubeContentPlan(
                workspace_id=workspace.id,
                created_by=owner.id,
                horizon_days=7,
                niche="AI",
                language="en",
                region="US",
                goal="awareness",
                status="completed",
                request_json={},
                result_json={},
            )
            db.add(plan)
            db.flush()
            initial_item = item_payload()
            breakdown = calculate_growth_opportunity_score(initial_item.topic, score_components())
            initial_item = initial_item.model_copy(
                update={"opportunity_score": breakdown.total_score, "score_explanation": breakdown.explanation}
            )
            record = YouTubeContentPlanItem(
                workspace_id=workspace.id,
                plan_id=plan.id,
                position=0,
                publish_date=initial_item.publish_date.isoformat(),
                item_json=initial_item.model_dump(mode="json"),
                score_components_json=breakdown.model_dump(mode="json"),
                opportunity_score=breakdown.total_score,
                confidence=initial_item.confidence,
                approved=False,
            )
            db.add(record)
            db.commit()
            self.owner_id = owner.id
            self.workspace_id = workspace.id
            self.plan_id = plan.id
            self.item_id = record.id

        self.current_user_id = self.owner_id
        test_app = FastAPI()
        test_app.include_router(router)

        def override_db():
            with self.session_factory() as db:
                yield db

        def override_user(db: Session = Depends(get_db)) -> User:
            user = db.get(User, self.current_user_id)
            assert user is not None
            return user

        test_app.dependency_overrides[get_db] = override_db
        test_app.dependency_overrides[get_current_user] = override_user
        self.client = TestClient(test_app)

    def tearDown(self) -> None:
        self.client.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_edit_and_approve_preserves_score_without_new_components(self) -> None:
        response = self.client.patch(
            f"/api/youtube-growth/content-plans/{self.plan_id}/items/{self.item_id}",
            json={
                "topic": "Edited source-backed topic",
                "titles": ["Edited A", "Edited B", "Edited C"],
                "approved": True,
            },
        )

        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual(self.item_id, body["id"])
        self.assertTrue(body["approved"])
        self.assertEqual("Edited source-backed topic", body["item"]["topic"])
        self.assertEqual(60, body["item"]["opportunity_score"])
        self.assertEqual(60, body["score_breakdown"]["total_score"])
        self.assertEqual("Edited source-backed topic", body["score_breakdown"]["topic"])
        with self.session_factory() as db:
            record = db.get(YouTubeContentPlanItem, self.item_id)
            plan = db.get(YouTubeContentPlan, self.plan_id)
            self.assertTrue(record.approved)
            self.assertEqual("Edited source-backed topic", record.item_json["topic"])
            self.assertEqual("Edited source-backed topic", plan.result_json["items"][0]["topic"])

    def test_components_are_validated_and_score_is_recomputed(self) -> None:
        components = score_components(100).model_dump(mode="json")
        response = self.client.patch(
            f"/api/youtube-growth/content-plans/{self.plan_id}/items/{self.item_id}",
            json={"score_components": components},
        )

        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual(100, body["item"]["opportunity_score"])
        self.assertEqual(100, body["score_breakdown"]["total_score"])
        self.assertIn("25% topic demand", body["item"]["score_explanation"])

    def test_invalid_patch_schema_is_rejected_before_mutation(self) -> None:
        endpoint = f"/api/youtube-growth/content-plans/{self.plan_id}/items/{self.item_id}"
        self.assertEqual(422, self.client.patch(endpoint, json={}).status_code)
        self.assertEqual(422, self.client.patch(endpoint, json={"titles": ["Only", "Two"]}).status_code)
        self.assertEqual(422, self.client.patch(endpoint, json={"opportunity_score": 99}).status_code)
        self.assertEqual(422, self.client.patch(endpoint, json={"approved": None}).status_code)
        with self.session_factory() as db:
            record = db.get(YouTubeContentPlanItem, self.item_id)
            self.assertFalse(record.approved)
            self.assertEqual("Original topic", record.item_json["topic"])

    def test_cross_workspace_user_cannot_edit(self) -> None:
        with self.session_factory() as db:
            other = User(email="foreign-plan-user@example.com")
            db.add(other)
            db.flush()
            workspace = Workspace(name="Foreign", slug="foreign-plan-workspace", owner_id=other.id)
            db.add(workspace)
            db.flush()
            db.add(WorkspaceMember(workspace_id=workspace.id, user_id=other.id, role="owner"))
            db.commit()
            self.current_user_id = other.id

        response = self.client.patch(
            f"/api/youtube-growth/content-plans/{self.plan_id}/items/{self.item_id}",
            json={"approved": True},
        )
        self.assertEqual(403, response.status_code, response.text)

    def test_viewer_cannot_edit_or_approve(self) -> None:
        with self.session_factory() as db:
            viewer = User(email="plan-viewer@example.com")
            db.add(viewer)
            db.flush()
            db.add(WorkspaceMember(workspace_id=self.workspace_id, user_id=viewer.id, role="viewer"))
            db.commit()
            self.current_user_id = viewer.id

        response = self.client.patch(
            f"/api/youtube-growth/content-plans/{self.plan_id}/items/{self.item_id}",
            json={"approved": True},
        )
        self.assertEqual(403, response.status_code, response.text)

    def test_item_must_belong_to_the_plan_in_the_same_workspace(self) -> None:
        with self.session_factory() as db:
            second_plan = YouTubeContentPlan(
                workspace_id=self.workspace_id,
                created_by=self.owner_id,
                horizon_days=7,
                niche="AI",
                language="en",
                region="US",
                goal="awareness",
                status="completed",
                request_json={},
                result_json={},
            )
            db.add(second_plan)
            db.flush()
            second_item = item_payload("Second plan topic")
            breakdown = calculate_growth_opportunity_score(second_item.topic, score_components())
            record = YouTubeContentPlanItem(
                workspace_id=self.workspace_id,
                plan_id=second_plan.id,
                position=0,
                publish_date=second_item.publish_date.isoformat(),
                item_json=second_item.model_dump(mode="json"),
                score_components_json=breakdown.model_dump(mode="json"),
                opportunity_score=breakdown.total_score,
                confidence=second_item.confidence,
                approved=False,
            )
            db.add(record)
            db.commit()
            foreign_item_id = record.id

        response = self.client.patch(
            f"/api/youtube-growth/content-plans/{self.plan_id}/items/{foreign_item_id}",
            json={"approved": True},
        )
        self.assertEqual(404, response.status_code, response.text)


if __name__ == "__main__":
    unittest.main()
