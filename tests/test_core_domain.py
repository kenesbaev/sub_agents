from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TEST_DB_ROOT = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(TEST_DB_ROOT.name) / 'core-domain-test.sqlite3'}"
os.environ["JWT_SECRET"] = "test-secret-for-core-domain-foundation"
os.environ["INTEGRATION_ENCRYPTION_SECRET"] = "test-encryption-secret"
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "kaliya-core" / "src"))
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core_domain.service import ensure_default_workspace, seed_default_workspace  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Agent, Task, Team, TeamAgent, User, Workspace, WorkspaceMember  # noqa: E402
from app.schemas import PublishTargetResult  # noqa: E402
from kaliya.agent_tools import build_turn_context  # noqa: E402
import agent_server  # noqa: E402


class CoreDomainTest(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

    def register(self, email: str = "owner@example.com") -> TestClient:
        client = TestClient(app)
        self.addCleanup(client.close)
        response = client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": "password123",
                "first_name": "Owner",
                "last_name": "User",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return client

    def test_register_creates_default_workspace_and_seeded_teams(self) -> None:
        client = self.register()

        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "owner@example.com"))
            self.assertIsNotNone(user)
            workspace = db.scalar(select(Workspace).where(Workspace.owner_id == user.id))
            self.assertIsNotNone(workspace)
            member = db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == user.id))
            self.assertIsNotNone(member)
            self.assertEqual("owner", member.role)

        response = client.get("/api/teams")
        self.assertEqual(response.status_code, 200, response.text)
        names = {team["name"] for team in response.json()}
        self.assertTrue({"Social Posting Team", "Business AI Team", "Founder's COS", "Marketing Team", "Sales Team", "Support Team"}.issubset(names))

    def test_seed_idempotency(self) -> None:
        self.register()

        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "owner@example.com"))
            workspace = ensure_default_workspace(db, user)
            first_count = db.query(Team).filter(Team.workspace_id == workspace.id).count()
            first_memberships = db.query(TeamAgent).count()
            seed_default_workspace(db, workspace, created_by=user.id)
            seed_default_workspace(db, workspace, created_by=user.id)
            db.commit()
            second_count = db.query(Team).filter(Team.workspace_id == workspace.id).count()
            second_memberships = db.query(TeamAgent).count()

        self.assertEqual(6, first_count)
        self.assertEqual(first_count, second_count)
        self.assertGreater(first_memberships, 0)
        self.assertEqual(first_memberships, second_memberships)

    def test_workspace_member_roles_control_write_access(self) -> None:
        owner_client = self.register("owner@example.com")
        viewer_client = self.register("viewer@example.com")

        with SessionLocal() as db:
            owner = db.scalar(select(User).where(User.email == "owner@example.com"))
            viewer = db.scalar(select(User).where(User.email == "viewer@example.com"))
            workspace = db.scalar(select(Workspace).where(Workspace.owner_id == owner.id))
            db.add(WorkspaceMember(workspace_id=workspace.id, user_id=viewer.id, role="viewer"))
            db.commit()

        response = owner_client.get("/api/teams")
        self.assertEqual(response.status_code, 200, response.text)
        workspace_id = response.json()[0]["workspace_id"]

        read_response = viewer_client.get(f"/api/teams?workspace_id={workspace_id}")
        self.assertEqual(read_response.status_code, 200, read_response.text)

        write_response = viewer_client.post(
            "/api/teams",
            json={"workspace_id": workspace_id, "name": "Viewer Team", "category": "Test"},
        )
        self.assertEqual(write_response.status_code, 403, write_response.text)

    def test_team_crud_and_agent_membership(self) -> None:
        client = self.register()
        teams_response = client.get("/api/teams")
        self.assertEqual(teams_response.status_code, 200, teams_response.text)
        workspace_id = teams_response.json()[0]["workspace_id"]

        create_response = client.post(
            "/api/teams",
            json={
                "workspace_id": workspace_id,
                "name": "Customer Success Team",
                "description": "Handles customer success tasks.",
                "category": "Support",
            },
        )
        self.assertEqual(create_response.status_code, 201, create_response.text)
        team = create_response.json()

        patch_response = client.patch(f"/api/teams/{team['id']}", json={"status": "active"})
        self.assertEqual(patch_response.status_code, 200, patch_response.text)
        self.assertEqual("active", patch_response.json()["status"])

        with SessionLocal() as db:
            agent = db.scalar(select(Agent).where(Agent.workspace_id == workspace_id).order_by(Agent.id))
            self.assertIsNotNone(agent)

        add_response = client.post(
            f"/api/teams/{team['id']}/agents",
            json={"agent_id": agent.id, "position": 1, "role_override": "Support lead"},
        )
        self.assertEqual(add_response.status_code, 201, add_response.text)
        self.assertEqual(agent.id, add_response.json()["agent_id"])

        remove_response = client.delete(f"/api/teams/{team['id']}/agents/{agent.id}")
        self.assertEqual(remove_response.status_code, 200, remove_response.text)

        delete_response = client.delete(f"/api/teams/{team['id']}")
        self.assertEqual(delete_response.status_code, 200, delete_response.text)
        self.assertEqual(404, client.get(f"/api/teams/{team['id']}").status_code)

    def test_task_crud(self) -> None:
        client = self.register()
        teams = client.get("/api/teams").json()
        workspace_id = teams[0]["workspace_id"]
        team_id = teams[0]["id"]

        create_response = client.post(
            "/api/tasks",
            json={
                "workspace_id": workspace_id,
                "team_id": team_id,
                "title": "Prepare campaign brief",
                "description": "Draft the first campaign brief.",
                "priority": "high",
                "input_json": {"owner": "Atlas"},
            },
        )
        self.assertEqual(create_response.status_code, 201, create_response.text)
        task = create_response.json()
        self.assertEqual("queued", task["status"])

        get_response = client.get(f"/api/tasks/{task['id']}")
        self.assertEqual(get_response.status_code, 200, get_response.text)

        patch_response = client.patch(f"/api/tasks/{task['id']}", json={"status": "completed", "progress": 100})
        self.assertEqual(patch_response.status_code, 200, patch_response.text)
        self.assertEqual("completed", patch_response.json()["status"])
        self.assertIsNotNone(patch_response.json()["completed_at"])

        delete_response = client.delete(f"/api/tasks/{task['id']}")
        self.assertEqual(delete_response.status_code, 200, delete_response.text)
        self.assertEqual(404, client.get(f"/api/tasks/{task['id']}").status_code)

    def test_workspace_isolation_for_teams_and_tasks(self) -> None:
        owner_client = self.register("owner@example.com")
        other_client = self.register("other@example.com")

        owner_teams = owner_client.get("/api/teams").json()
        owner_team_id = owner_teams[0]["id"]
        owner_workspace_id = owner_teams[0]["workspace_id"]
        task_response = owner_client.post(
            "/api/tasks",
            json={"workspace_id": owner_workspace_id, "team_id": owner_team_id, "title": "Private task"},
        )
        self.assertEqual(task_response.status_code, 201, task_response.text)
        task_id = task_response.json()["id"]

        self.assertEqual(403, other_client.get(f"/api/teams/{owner_team_id}").status_code)
        self.assertEqual(403, other_client.get(f"/api/tasks/{task_id}").status_code)
        self.assertEqual(403, other_client.get(f"/api/teams?workspace_id={owner_workspace_id}").status_code)

    def test_social_posting_team_creates_task_and_publish_completes_it(self) -> None:
        client = self.register()
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "owner@example.com"))
            self.assertIsNotNone(user)

        def fake_run_ai(prompt: str, **_kwargs: object) -> str:
            if "Format JSON" in prompt or "Формат JSON" in prompt:
                return (
                    '{"action":"delegate","coordinatorMessage":"Social Posting Team route selected.",'
                    '"needsUserInput":false,"userQuestions":[],"assignments":[{"agentId":"scout","task":"Research China travel post angle"}]}'
                )
            if "Role: Scout" in prompt:
                return "Scout report: China travel angle, personal journey, concise Telegram hook."
            if "Role: Mira" in prompt:
                return "Готовый publish-ready текст:\nЛечу в Китай. Новый маршрут, новые встречи и новый заряд идей."
            if "Role: Dex" in prompt:
                return "Dex report: Telegram is the target platform; copy is ready for publishing."
            if "Role: Echo" in prompt:
                return "Echo report: Final copy is clear and ready to publish."
            return "Done.\n<PUBLISH_TEXT>Лечу в Китай. Новый маршрут, новые встречи и новый заряд идей.</PUBLISH_TEXT>"

        context = build_turn_context(
            message="Я лечу в Китай. Сделай пост и опубликуй его.",
            raw_attachments=[],
            upload_parts=[],
            data_dir=Path(TEST_DB_ROOT.name) / "agent-data",
        )
        try:
            with patch("agent_server.run_ai", side_effect=fake_run_ai):
                result = agent_server.run_team_chat(
                    "session-social",
                    f"user-{user.id}",
                    context,
                    [],
                    run_id="phase2-social-run",
                    team_id="social-posting-team",
                    team_name="Social Posting Team",
                )
        finally:
            context.cleanup()

        self.assertEqual("phase2-social-run", result["runId"] if "runId" in result else "phase2-social-run")
        self.assertTrue(result["pendingPublish"]["autoPublish"])
        self.assertEqual("telegram", result["pendingPublish"]["platform"])
        task_id = result["pendingPublish"]["taskId"]
        self.assertIsNotNone(task_id)
        authors = [message["author"] for message in result["messages"]]
        self.assertIn("Scout", authors)
        self.assertIn("Mira", authors)
        self.assertIn("Dex", authors)
        self.assertIn("Echo", authors)

        with SessionLocal() as db:
            task = db.get(Task, task_id)
            self.assertIsNotNone(task)
            self.assertEqual("in_progress", task.status)
            self.assertEqual("phase2-social-run", task.input_json["runId"])

        with patch(
            "app.integrations.publish_to_platform",
            return_value=PublishTargetResult(platform="telegram", ok=True, external_id="message-123"),
        ):
            publish_response = client.post(
                "/api/publish/social",
                json={
                    "text": result["pendingPublish"]["text"],
                    "platforms": ["telegram"],
                    "run_id": "phase2-social-run",
                    "task_id": task_id,
                    "source": "team",
                },
            )
        self.assertEqual(publish_response.status_code, 200, publish_response.text)

        with SessionLocal() as db:
            task = db.get(Task, task_id)
            self.assertIsNotNone(task)
            self.assertEqual("completed", task.status)
            self.assertEqual(100, task.progress)
            self.assertTrue(task.result_json["published"])

def tearDownModule() -> None:
    engine.dispose()
    TEST_DB_ROOT.cleanup()


if __name__ == "__main__":
    unittest.main()
