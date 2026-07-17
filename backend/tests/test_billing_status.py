from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.billing.router import plan_summary, router
from app.db.base import Base
from app.db.session import get_db
from app.models import User, Workspace, WorkspaceMember
from app.security import get_current_user


@pytest.fixture
def billing_api():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    with session_factory.begin() as db:
        owner = User(email="owner@example.com")
        member = User(email="member@example.com")
        outsider = User(email="outsider@example.com")
        db.add_all([owner, member, outsider])
        db.flush()

        workspace = Workspace(name="Owner workspace", slug="owner-workspace", owner_id=owner.id)
        outsider_workspace = Workspace(name="Outside workspace", slug="outside-workspace", owner_id=outsider.id)
        db.add_all([workspace, outsider_workspace])
        db.flush()
        db.add_all(
            [
                WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role="owner"),
                WorkspaceMember(workspace_id=workspace.id, user_id=member.id, role="member"),
                WorkspaceMember(workspace_id=outsider_workspace.id, user_id=outsider.id, role="owner"),
            ]
        )

    current_user_id = [owner.id]
    app = FastAPI()
    app.include_router(router)

    def override_db():
        with session_factory() as db:
            yield db

    def override_user(db: Session = Depends(get_db)) -> User:
        user = db.get(User, current_user_id[0])
        assert user is not None
        return user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    client = TestClient(app)
    state = SimpleNamespace(
        app=app,
        client=client,
        current_user_id=current_user_id,
        member_id=member.id,
        outsider_id=outsider.id,
        session_factory=session_factory,
        workspace_id=workspace.id,
    )
    try:
        yield state
    finally:
        client.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_owner_without_plan_can_upgrade(billing_api) -> None:
    response = billing_api.client.get("/api/billing/status")

    assert response.status_code == 200
    assert response.json() == {
        "workspaceId": billing_api.workspace_id,
        "role": "owner",
        "plan": None,
        "canUpgrade": True,
    }


@pytest.mark.parametrize(
    ("plan_code", "plan_name"),
    [("start", "Start"), ("plus", "Plus"), ("pro", "Pro"), ("custom", "Custom")],
)
def test_assigned_plan_is_normalized_and_hides_upgrade(billing_api, plan_code: str, plan_name: str) -> None:
    with billing_api.session_factory.begin() as db:
        workspace = db.get(Workspace, billing_api.workspace_id)
        assert workspace is not None
        workspace.plan_code = plan_code

    response = billing_api.client.get("/api/billing/status")

    assert response.status_code == 200
    assert response.json()["plan"] == {"code": plan_code, "name": plan_name}
    assert response.json()["canUpgrade"] is False


def test_member_without_plan_can_read_status_but_cannot_upgrade(billing_api) -> None:
    billing_api.current_user_id[0] = billing_api.member_id

    response = billing_api.client.get(f"/api/billing/status?workspace_id={billing_api.workspace_id}")

    assert response.status_code == 200
    assert response.json() == {
        "workspaceId": billing_api.workspace_id,
        "role": "member",
        "plan": None,
        "canUpgrade": False,
    }


def test_non_member_cannot_read_workspace_plan(billing_api) -> None:
    billing_api.current_user_id[0] = billing_api.outsider_id

    response = billing_api.client.get(f"/api/billing/status?workspace_id={billing_api.workspace_id}")

    assert response.status_code == 403


def test_status_requires_authentication(billing_api) -> None:
    billing_api.app.dependency_overrides.pop(get_current_user)

    response = billing_api.client.get("/api/billing/status")

    assert response.status_code == 401


def test_invalid_persisted_plan_fails_closed() -> None:
    workspace = Workspace(id=42, name="Invalid", slug="invalid", owner_id=1, plan_code="enterprise")

    with pytest.raises(HTTPException) as exc_info:
        plan_summary(workspace)

    assert exc_info.value.status_code == 500


def test_router_exposes_only_read_only_status_endpoint() -> None:
    methods_by_path = {(route.path, frozenset(route.methods or set())) for route in router.routes}

    assert methods_by_path == {("/api/billing/status", frozenset({"GET"}))}
