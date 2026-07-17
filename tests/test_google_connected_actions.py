from __future__ import annotations

import asyncio
import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
TEST_DB_ROOT = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(TEST_DB_ROOT.name) / 'google-actions-test.sqlite3'}"
sys.path.insert(0, str(ROOT / "backend"))

from app.connected_apps.google_actions import (  # noqa: E402
    GOOGLE_TOOL_SCOPES,
    GoogleCredentials,
    GoogleToolExecution,
    execute_google_agent_tool,
    load_google_credentials,
)
from app.connected_apps.google_oauth import google_connected_scopes  # noqa: E402
from app.connected_apps.router import AgentToolExecuteRequest, execute_agent_tool  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models import IntegrationAccount, IntegrationProvider, IntegrationToken, User, UserIntegration  # noqa: E402


ALL_GOOGLE_SCOPES = frozenset(
    {
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.freebusy",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/spreadsheets",
    }
)


class GoogleConnectedActionsTest(unittest.TestCase):
    def credentials(self, scopes: frozenset[str] = ALL_GOOGLE_SCOPES) -> GoogleCredentials:
        return GoogleCredentials(account_id=17, access_token="oauth-access-token", scopes=scopes)

    def execute(self, tool: str, arguments: dict[str, object], responses: list[dict[str, object]]) -> tuple[GoogleToolExecution, list[dict[str, object]]]:
        calls: list[dict[str, object]] = []

        async def fake_google_request(
            access_token: str,
            method: str,
            url: str,
            *,
            params: dict[str, object] | None = None,
            json_body: dict[str, object] | None = None,
        ) -> dict[str, object]:
            calls.append(
                {
                    "access_token": access_token,
                    "method": method,
                    "url": url,
                    "params": params or {},
                    "json": json_body or {},
                }
            )
            return responses.pop(0)

        with (
            patch("app.connected_apps.google_actions.load_google_credentials", return_value=self.credentials()),
            patch("app.connected_apps.google_actions.google_api_request", new=fake_google_request),
        ):
            execution = asyncio.run(execute_google_agent_tool(MagicMock(), user_id=4, tool=tool, arguments=arguments))
        return execution, calls

    def test_send_gmail_requires_approval_and_uses_raw_message(self) -> None:
        with patch("app.connected_apps.google_actions.load_google_credentials", return_value=self.credentials()):
            with self.assertRaisesRegex(Exception, "explicit approval"):
                asyncio.run(
                    execute_google_agent_tool(
                        MagicMock(),
                        user_id=4,
                        tool="send_gmail",
                        arguments={"to": "person@example.com", "subject": "Hello", "body": "Body"},
                    )
                )

        execution, calls = self.execute(
            "send_gmail",
            {"to": ["person@example.com"], "subject": "Hello", "body": "Body", "approved": True},
            [{"id": "message-1", "threadId": "thread-1", "labelIds": ["SENT"]}],
        )

        self.assertEqual({"messageId": "message-1", "threadId": "thread-1", "labelIds": ["SENT"]}, execution.result)
        self.assertEqual("POST", calls[0]["method"])
        self.assertTrue(str(calls[0]["url"]).endswith("/gmail/v1/users/me/messages/send"))
        raw = str(calls[0]["json"]["raw"])
        decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
        self.assertIn("To: person@example.com", decoded)
        self.assertIn("Subject: Hello", decoded)
        self.assertNotIn("oauth-access-token", raw)

    def test_gmail_draft_requires_approval(self) -> None:
        with patch("app.connected_apps.google_actions.load_google_credentials", return_value=self.credentials()):
            with self.assertRaisesRegex(Exception, "explicit approval"):
                asyncio.run(
                    execute_google_agent_tool(
                        MagicMock(),
                        user_id=4,
                        tool="create_gmail_draft",
                        arguments={"to": "person@example.com", "subject": "Hello", "body": "Body"},
                    )
                )

        execution, calls = self.execute(
            "create_gmail_draft",
            {"to": ["person@example.com"], "subject": "Hello", "body": "Body", "approved": True},
            [{"id": "draft-1", "message": {"id": "message-1", "threadId": "thread-1"}}],
        )
        self.assertEqual({"draftId": "draft-1", "messageId": "message-1", "threadId": "thread-1"}, execution.result)
        self.assertEqual("POST", calls[0]["method"])
        self.assertTrue(str(calls[0]["url"]).endswith("/gmail/v1/users/me/drafts"))

    def test_connected_google_scopes_cover_each_dispatched_tool(self) -> None:
        granted_on_connect = set(google_connected_scopes())
        for tool, acceptable_scopes in GOOGLE_TOOL_SCOPES.items():
            self.assertTrue(granted_on_connect.intersection(acceptable_scopes), tool)

    def test_calendar_reads_and_creates_without_guest_notifications(self) -> None:
        execution, calls = self.execute(
            "list_calendar_events",
            {
                "time_min": "2026-07-13T09:00:00Z",
                "time_max": "2026-07-13T18:00:00Z",
                "max_results": 5,
            },
            [{"items": [{"id": "event-1", "summary": "Planning", "start": {}, "end": {}}]}],
        )
        self.assertEqual("event-1", execution.result["events"][0]["id"])
        self.assertEqual("GET", calls[0]["method"])
        self.assertTrue(str(calls[0]["url"]).endswith("/calendar/v3/calendars/primary/events"))

        execution, calls = self.execute(
            "create_calendar_event",
            {
                "summary": "Planning",
                "start": "2026-07-13T09:00:00Z",
                "end": "2026-07-13T10:00:00Z",
                "approved": True,
            },
            [{"id": "event-2", "summary": "Planning", "start": {}, "end": {}, "htmlLink": "https://calendar.example/event-2"}],
        )
        self.assertEqual("event-2", execution.result["id"])
        self.assertEqual("POST", calls[0]["method"])
        self.assertEqual("none", calls[0]["params"]["sendUpdates"])
        self.assertNotIn("attendees", calls[0]["json"])

    def test_sheets_read_append_and_scope_guard(self) -> None:
        execution, calls = self.execute(
            "read_google_sheet",
            {"spreadsheet_id": "sheet-id", "range": "Leads!A1:B5"},
            [{"spreadsheetId": "sheet-id", "range": "Leads!A1:B5", "majorDimension": "ROWS", "values": [["name", "email"]]}],
        )
        self.assertEqual([["name", "email"]], execution.result["values"])
        self.assertEqual("GET", calls[0]["method"])

        execution, calls = self.execute(
            "append_google_sheet_row",
            {"spreadsheet_id": "sheet-id", "range": "Leads!A:B", "row": ["Ada", "ada@example.com"], "approved": True},
            [{"spreadsheetId": "sheet-id", "tableRange": "Leads!A1:B1", "updates": {"updatedRange": "Leads!A2:B2", "updatedRows": 1, "updatedCells": 2}}],
        )
        self.assertEqual("Leads!A2:B2", execution.result["updatedRange"])
        self.assertEqual("POST", calls[0]["method"])
        self.assertEqual([["Ada", "ada@example.com"]], calls[0]["json"]["values"])

        with patch(
            "app.connected_apps.google_actions.load_google_credentials",
            return_value=self.credentials(frozenset({"https://www.googleapis.com/auth/gmail.readonly"})),
        ):
            with self.assertRaisesRegex(Exception, "missing the required permission"):
                asyncio.run(
                    execute_google_agent_tool(
                        MagicMock(),
                        user_id=4,
                        tool="read_google_sheet",
                        arguments={"spreadsheet_id": "sheet-id", "range": "Leads!A1"},
                    )
                )

        with patch(
            "app.connected_apps.google_actions.load_google_credentials",
            return_value=self.credentials(frozenset()),
        ):
            with self.assertRaisesRegex(Exception, "missing the required permission"):
                asyncio.run(
                    execute_google_agent_tool(
                        MagicMock(),
                        user_id=4,
                        tool="read_google_sheet",
                        arguments={"spreadsheet_id": "sheet-id", "range": "Leads!A1"},
                    )
                )

    def test_encrypted_google_token_is_loaded_from_the_users_account(self) -> None:
        engine = create_engine("sqlite://")
        Base.metadata.create_all(bind=engine)
        try:
            with Session(engine) as db:
                user = User(email="owner@example.com")
                provider = IntegrationProvider(key="google", name="Google", auth_type="oauth2")
                db.add_all([user, provider])
                db.flush()
                integration = UserIntegration(user_id=user.id, provider_id=provider.id, status="connected")
                db.add(integration)
                db.flush()
                account = IntegrationAccount(
                    user_integration_id=integration.id,
                    provider_id=provider.id,
                    account_identifier="owner@example.com",
                    account_label="Owner",
                    account_type="google_workspace",
                    is_default=True,
                )
                db.add(account)
                db.flush()
                db.add(
                    IntegrationToken(
                        user_integration_id=integration.id,
                        integration_account_id=account.id,
                        encrypted_access_token="ciphertext",
                        scopes="https://www.googleapis.com/auth/spreadsheets",
                    )
                )
                db.commit()

                with patch("app.connected_apps.google_actions.decrypt_token", return_value="decrypted-oauth-token") as decrypt:
                    credentials = load_google_credentials(db, user_id=user.id)
                decrypt.assert_called_once_with("ciphertext")
                self.assertEqual("decrypted-oauth-token", credentials.access_token)
                self.assertEqual(account.id, credentials.account_id)
                self.assertIn("https://www.googleapis.com/auth/spreadsheets", credentials.scopes)
        finally:
            Base.metadata.drop_all(bind=engine)

    def test_agent_tools_endpoint_dispatches_google_actions(self) -> None:
        db = MagicMock()
        user = SimpleNamespace(id=4)
        execution = GoogleToolExecution(account_id=17, result={"messageId": "message-1"})
        with (
            patch("app.connected_apps.router.is_google_agent_tool", return_value=True),
            patch("app.connected_apps.router.get_settings", return_value=SimpleNamespace(is_production=False)),
            patch("app.connected_apps.router.refresh_due_oauth_tokens", new=AsyncMock()),
            patch("app.connected_apps.router.execute_google_agent_tool", new=AsyncMock(return_value=execution)),
        ):
            result = asyncio.run(
                execute_agent_tool(
                    AgentToolExecuteRequest(tool="send_gmail", arguments={"approved": True, "agent": "mika"}),
                    user=user,
                    db=db,
                )
            )
        self.assertEqual({"ok": True, "result": {"messageId": "message-1"}}, result)
        db.commit.assert_called_once()
        db.add.assert_called_once()

    def test_production_blocks_google_write_actions_before_dispatch(self) -> None:
        db = MagicMock()
        dispatcher = AsyncMock()
        with (
            patch("app.connected_apps.router.is_google_agent_tool", return_value=True),
            patch("app.connected_apps.router.get_settings", return_value=SimpleNamespace(is_production=True)),
            patch("app.connected_apps.router.execute_google_agent_tool", new=dispatcher),
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    execute_agent_tool(
                        AgentToolExecuteRequest(tool="send_gmail", arguments={"approved": True}),
                        user=SimpleNamespace(id=4),
                        db=db,
                    )
                )

        self.assertEqual(403, raised.exception.status_code)
        dispatcher.assert_not_awaited()
        db.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
