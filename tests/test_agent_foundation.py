from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kaliya-core" / "src"))

import agent_server  # noqa: E402
from kaliya.agent_memory import AgentMemoryStore  # noqa: E402
from kaliya.agent_tools import build_turn_context  # noqa: E402
from kaliya.link_reader import fetch_link_summary  # noqa: E402
from kaliya.local_crm import LocalCRM  # noqa: E402


class AgentFoundationTest(unittest.TestCase):
    def test_agent_server_main_starts_and_closes_http_server(self) -> None:
        with (
            patch.object(sys, "argv", ["agent_server.py", "--host", "127.0.0.1", "--port", "0"]),
            patch.object(agent_server, "production_config_errors", return_value=[]),
            patch.object(agent_server.os, "chdir"),
            patch.object(agent_server, "ProductionAgentHTTPServer") as server_class,
        ):
            agent_server.main()

        server_class.assert_called_once_with(("127.0.0.1", 0), agent_server.AgentHandler)
        server_class.return_value.serve_forever.assert_called_once_with(poll_interval=0.5)
        server_class.return_value.server_close.assert_called_once_with()

    def test_memory_isolated_per_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "agent-memory"
            mika = AgentMemoryStore(root, account_id="local", agent_id="mika")
            scout = AgentMemoryStore(root, account_id="local", agent_id="scout")

            mika.remember(
                kind="lead",
                title="Salon lead",
                body="Client A wants a premium salon marketing package.",
            )

            self.assertIn("Client A", mika.context_for_prompt("premium salon package"))
            self.assertEqual("", scout.context_for_prompt("premium salon package"))

    def test_memory_redacts_secret_like_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AgentMemoryStore(Path(temp_dir), account_id="local", agent_id="dev")
            store.remember(
                kind="note",
                title="API note",
                body="Use api_key=sk-123456789012 for the integration.",
            )
            context = store.context_for_prompt("api integration")
            self.assertIn("<redacted>", context)
            self.assertNotIn("sk-123456789012", context)

    def test_memory_store_prunes_unbounded_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AgentMemoryStore(Path(temp_dir), account_id="bounded", agent_id="dev")
            with (
                patch("kaliya.agent_memory.MEMORY_MAX_MESSAGES", 3),
                patch("kaliya.agent_memory.MEMORY_MAX_ITEMS", 2),
            ):
                for index in range(5):
                    message_id = store.add_message(
                        role="user",
                        author="User",
                        text=f"message {index}",
                        event_type="chat",
                    )
                    store.remember(
                        kind="auto",
                        title=f"memory {index}",
                        body=f"bounded memory body {index} with enough distinct text",
                        source_message_id=message_id,
                    )

            with closing(sqlite3.connect(store.database_path)) as db:
                self.assertEqual(3, db.execute("select count(*) from messages").fetchone()[0])
                self.assertEqual(2, db.execute("select count(*) from memories").fetchone()[0])
                self.assertEqual(2, db.execute("select count(*) from memory_chunks").fetchone()[0])
                self.assertEqual(2, db.execute("select count(*) from memory_chunks_fts").fetchone()[0])

    def test_fresh_memory_and_crm_initialization_is_thread_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            def initialize(index: int) -> None:
                AgentMemoryStore(root / "memory", account_id="concurrent", agent_id="dev").add_message(
                    role="user",
                    author="User",
                    text=f"message {index}",
                    event_type="chat",
                )
                LocalCRM(root / "data", account_id="concurrent").note_interaction(
                    agent_id="dev",
                    message=f"client Test{index}",
                    summary=f"interaction {index}",
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(initialize, range(8)))

            memory_path = root / "memory" / "concurrent" / "dev" / "memory.sqlite3"
            crm_path = root / "data" / "crm" / "concurrent.sqlite3"
            with closing(sqlite3.connect(memory_path)) as db:
                self.assertEqual(8, db.execute("select count(*) from messages").fetchone()[0])
            with closing(sqlite3.connect(crm_path)) as db:
                self.assertEqual(8, db.execute("select count(*) from interactions").fetchone()[0])

    def test_link_reader_blocks_private_links(self) -> None:
        summary = asyncio.run(
            fetch_link_summary(
                "http://127.0.0.1:9999/private",
                timeout_seconds=1,
                max_bytes=1024,
            )
        )

        self.assertIn("blocked", summary.error.lower())

    def test_csv_upload_is_scoped_to_request_and_cleaned_up(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            context = build_turn_context(
                message="Проанализируй таблицу",
                raw_attachments=[],
                upload_parts=[
                    {
                        "name": "sales.csv",
                        "content_type": "text/csv",
                        "data": b"name,revenue\nA,100\nB,250\n",
                    }
                ],
                data_dir=data_dir,
            )
            attachment_path = context.attachments[0].path
            try:
                tool_context = context.tool_context
                self.assertIn("CSV context", tool_context)
                self.assertIn("Columns (2): name, revenue", tool_context)
                self.assertIn("this request only", tool_context)
                self.assertTrue(attachment_path.exists())
                self.assertFalse((data_dir / "tables").exists())
            finally:
                context.cleanup()
            self.assertFalse(attachment_path.exists())

    def test_run_codex_falls_back_from_model_and_search(self) -> None:
        attempts: list[tuple[str | None, bool]] = []

        def fake_run(
            _prompt: str,
            *,
            model: str | None,
            image_paths: list[Path],
            search_enabled: bool,
        ) -> str:
            attempts.append((model, search_enabled))
            if search_enabled:
                raise RuntimeError("unknown option --search")
            if model:
                raise RuntimeError("unknown model")
            return "ok"

        with patch("agent_server.shutil.which", return_value="/usr/bin/codex"):
            with patch("agent_server._run_codex_once", side_effect=fake_run):
                self.assertEqual("ok", agent_server.run_codex("hello", agent_id="mika"))

        self.assertEqual(("gpt-5.4", True), attempts[0])
        self.assertIn((None, False), attempts)

    def test_run_codex_uses_utf8_for_unicode_prompt(self) -> None:
        popen_kwargs: dict[str, object] = {}
        command: list[str] = []

        class FakeProcess:
            returncode = 0

            def communicate(self, input: str | None, timeout: float) -> tuple[str, str]:
                self.input = input
                return "ok", ""

        def fake_popen(*args: object, **kwargs: object) -> FakeProcess:
            command.extend(args[0])
            popen_kwargs.update(kwargs)
            return FakeProcess()

        with patch("agent_server.shutil.which", return_value="codex"):
            with patch("agent_server.subprocess.Popen", side_effect=fake_popen):
                self.assertEqual("ok", agent_server.run_codex("Я лечу в Китай 🚀", agent_id="mika"))

        self.assertEqual("utf-8", popen_kwargs.get("encoding"))
        self.assertEqual("replace", popen_kwargs.get("errors"))
        self.assertIn("--config", command)
        self.assertIn('model_reasoning_effort="xhigh"', command)

    def test_run_ai_hides_provider_error_details_when_both_backends_fail(self) -> None:
        with patch("agent_server.run_openrouter", side_effect=RuntimeError("primary-private-detail")):
            with patch("agent_server.run_codex", side_effect=RuntimeError("fallback-private-detail")):
                with self.assertRaises(agent_server.AgentBackendUnavailable) as raised:
                    agent_server.run_ai("hello")

        self.assertEqual(agent_server.AI_BACKEND_UNAVAILABLE_MESSAGE, str(raised.exception))
        self.assertNotIn("primary-private-detail", str(raised.exception))
        self.assertNotIn("fallback-private-detail", str(raised.exception))

    def test_openrouter_uses_a_credit_safe_output_limit(self) -> None:
        captured: dict[str, object] = {}

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"ok"}}]}'

        def fake_urlopen(request: object, **kwargs: object) -> FakeResponse:
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = kwargs.get("timeout")
            return FakeResponse()

        with agent_server.OPENROUTER_CIRCUIT_LOCK:
            agent_server.OPENROUTER_CIRCUITS.clear()
        with patch.dict("agent_server.os.environ", {"OPENROUTER_API_KEY": "test-key"}, clear=False):
            with patch("agent_server.urllib.request.urlopen", side_effect=fake_urlopen):
                self.assertEqual(
                    "ok",
                    agent_server.run_openrouter(
                        "hello",
                        agent_id="coordinator",
                        image_paths=[],
                        search_enabled=True,
                    ),
                )

        self.assertEqual(
            agent_server.OPENROUTER_MAX_TOKENS,
            captured["payload"]["max_tokens"],
        )
        self.assertEqual(agent_server.OPENROUTER_TIMEOUT_SECONDS, captured["timeout"])
        search_parameters = captured["payload"]["tools"][0]["parameters"]
        self.assertEqual(agent_server.OPENROUTER_WEB_MAX_RESULTS, search_parameters["max_results"])
        self.assertEqual(agent_server.OPENROUTER_WEB_MAX_TOTAL_RESULTS, search_parameters["max_total_results"])

    def test_openrouter_search_and_circuit_are_bounded_per_model(self) -> None:
        first_model = "provider/model-a"
        second_model = "provider/model-b"
        with agent_server.OPENROUTER_CIRCUIT_LOCK:
            agent_server.OPENROUTER_CIRCUITS.clear()
        with patch.object(agent_server, "OPENROUTER_CIRCUIT_FAILURE_THRESHOLD", 2):
            agent_server.record_openrouter_failure(first_model)
            agent_server.record_openrouter_failure(first_model)
            self.assertFalse(agent_server.openrouter_circuit_allows_request(first_model))
            self.assertTrue(agent_server.openrouter_circuit_allows_request(second_model))
        agent_server.record_openrouter_success(first_model)
        self.assertTrue(agent_server.openrouter_circuit_allows_request(first_model))

    def test_session_cookie_derives_account_id_from_signed_subject(self) -> None:
        secret = "test-session-secret-with-at-least-thirty-two-characters"
        token = agent_server.jwt.encode(
            {"sub": "42", "exp": int(time.time()) + 60},
            secret,
            algorithm="HS256",
        )
        with patch.dict(
            agent_server.os.environ,
            {"JWT_SECRET": secret, "JWT_ALGORITHM": "HS256"},
            clear=False,
        ):
            account_id = agent_server.decode_session_account_id(f"rebly_session={token}")
        self.assertEqual("user-42", account_id)

    def test_cancel_cannot_cross_account_boundary(self) -> None:
        run_id = "ownership-test-run"
        agent_server.start_agent_run(
            run_id,
            agent_id="coordinator",
            session_id="session-1",
            account_id="user-1",
            message="hello",
        )
        try:
            self.assertFalse(agent_server.request_agent_run_cancel(run_id, account_id="user-2"))
            self.assertTrue(agent_server.request_agent_run_cancel(run_id, account_id="user-1"))
        finally:
            agent_server.finish_agent_run(run_id)

    def test_run_deadline_is_enforced_before_another_provider_phase(self) -> None:
        run_id = "deadline-test-run"
        agent_server.start_agent_run(
            run_id,
            agent_id="all",
            session_id="session-deadline",
            account_id="user-1",
            message="long team task",
        )
        try:
            with agent_server.ACTIVE_AGENT_RUNS_LOCK:
                agent_server.ACTIVE_AGENT_RUNS[run_id]["deadline"] = time.monotonic() - 1
            with self.assertRaises(agent_server.AgentRunTimedOut):
                agent_server.check_agent_run_cancelled(run_id)
        finally:
            agent_server.finish_agent_run(run_id)

    def test_team_requests_are_charged_by_provider_fanout(self) -> None:
        account_id = "rate-cost-user"
        with agent_server.AGENT_RATE_LIMIT_LOCK:
            agent_server.AGENT_RATE_LIMIT_BUCKETS.pop(account_id, None)
        cost = agent_server.AGENT_TEAM_RATE_COST
        with patch.object(agent_server, "AGENT_RATE_LIMIT_PER_MINUTE", cost * 2):
            self.assertTrue(agent_server.consume_agent_rate_limit(account_id, cost=cost)[0])
            self.assertTrue(agent_server.consume_agent_rate_limit(account_id, cost=cost)[0])
            self.assertFalse(agent_server.consume_agent_rate_limit(account_id, cost=cost)[0])
        with agent_server.AGENT_RATE_LIMIT_LOCK:
            agent_server.AGENT_RATE_LIMIT_BUCKETS.pop(account_id, None)

    def test_run_ai_preserves_agent_run_cancelled(self) -> None:
        with patch("agent_server.run_openrouter", side_effect=RuntimeError("primary failed")):
            with patch("agent_server.run_codex", side_effect=agent_server.AgentRunCancelled("cancel-me")):
                with self.assertRaises(agent_server.AgentRunCancelled):
                    agent_server.run_ai("hello", run_id="cancel-me")

    def test_social_team_provider_failure_never_creates_publish_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            context = build_turn_context(
                message="Prepare and publish a Telegram post about our launch.",
                raw_attachments=[],
                upload_parts=[],
                data_dir=Path(temp_dir),
            )
            try:
                with (
                    patch.object(agent_server, "DATA_DIR", Path(temp_dir)),
                    patch.object(agent_server, "MEMORY_ROOT", Path(temp_dir) / "memory"),
                    patch.object(agent_server, "run_ai", side_effect=RuntimeError("provider unavailable")),
                    patch.object(agent_server, "build_pending_publish") as pending_publish,
                ):
                    with self.assertRaises(agent_server.AgentBackendUnavailable):
                        agent_server.run_team_chat(
                            "provider-failure-session",
                            "local",
                            context,
                            [],
                            run_id="provider-failure-run",
                            team_id="social-posting-team",
                            team_name="Social Posting Team",
                        )
                pending_publish.assert_not_called()
            finally:
                context.cleanup()

    def test_pending_team_runs_have_per_account_cap_and_ttl(self) -> None:
        with agent_server.PENDING_TEAM_RUNS_LOCK:
            agent_server.PENDING_TEAM_RUNS.clear()
        try:
            with (
                patch.object(agent_server, "PENDING_TEAM_RUN_MAX_ENTRIES", 3),
                patch.object(agent_server, "PENDING_TEAM_RUN_MAX_PER_ACCOUNT", 1),
                patch.object(agent_server, "PENDING_TEAM_RUN_TTL_SECONDS", 1.0),
            ):
                agent_server.store_pending_team_run("user-1:first", account_id="user-1", run_id="one", message="one")
                agent_server.store_pending_team_run("user-1:second", account_id="user-1", run_id="two", message="two")
                self.assertNotIn("user-1:first", agent_server.PENDING_TEAM_RUNS)
                with agent_server.PENDING_TEAM_RUNS_LOCK:
                    agent_server.PENDING_TEAM_RUNS["user-2:expired"] = {
                        "accountId": "user-2",
                        "runId": "old",
                        "message": "old",
                        "createdMonotonic": time.monotonic() - 2,
                    }
                agent_server.store_pending_team_run("user-3:new", account_id="user-3", run_id="new", message="new")
                self.assertNotIn("user-2:expired", agent_server.PENDING_TEAM_RUNS)
        finally:
            with agent_server.PENDING_TEAM_RUNS_LOCK:
                agent_server.PENDING_TEAM_RUNS.clear()

    def test_youtube_publish_card_is_single_target_and_never_auto_publishes(self) -> None:
        message = (
            "Publish our launch video to YouTube and Instagram: "
            "https://cdn.example.com/launch.mp4"
        )
        pending = agent_server.build_pending_publish(
            message,
            "Final reply",
            "Meet the new Teamora AI launch video.",
            run_id="youtube-run-1",
            force_auto_publish=True,
        )

        self.assertTrue(agent_server.wants_social_publish(message))
        self.assertTrue(agent_server.wants_social_publish("\u041e\u043f\u0443\u0431\u043b\u0438\u043a\u0443\u0439 \u043d\u0430 \u044e\u0442\u044c\u044e\u0431."))
        self.assertIsNotNone(pending)
        self.assertEqual("youtube", pending["platform"])
        self.assertEqual(["youtube"], pending["platforms"])
        self.assertEqual("approval_required", pending["status"])
        self.assertFalse(pending["autoPublish"])
        self.assertEqual("https://cdn.example.com/launch.mp4", pending["mediaUrl"])
        self.assertEqual("Meet the new Teamora AI launch video.", pending["youtubeTitle"])
        self.assertEqual(pending["text"], pending["youtubeDescription"])
        self.assertEqual("private", pending["privacyStatus"])
        self.assertTrue(pending["separateActionRequired"])
        self.assertEqual(["instagram"], pending["separatePlatforms"])
        self.assertIn("separate", pending["notice"].lower())

    def test_production_never_auto_publishes_social_output(self) -> None:
        with (
            patch.object(agent_server, "IS_PRODUCTION", True),
            patch.dict(os.environ, {"TELEGRAM_AUTO_PUBLISH": "true"}),
        ):
            pending = agent_server.build_pending_publish(
                "Publish this announcement to Telegram",
                "The announcement is ready.",
                "Production announcement",
                run_id="production-approval-guard",
                force_auto_publish=True,
            )

        self.assertIsNotNone(pending)
        self.assertFalse(pending["autoPublish"])
        self.assertEqual("approval_required", pending["status"])

    def test_misspelled_youtube_never_falls_back_to_telegram(self) -> None:
        message = "\u0442\u0430\u043a \u043d\u0443\u0436\u043d\u043e \u0434\u0435\u043b\u0430\u0442\u044c \u043f\u043e\u0441\u0442 \u043d\u0430 yuotube"

        self.assertEqual(["youtube"], agent_server.publish_platforms(message))
        self.assertEqual(["youtube"], agent_server.publish_platforms("Upload this video to a YouTube channel"))
        for alias in ("yuotube", "yotube", "you tube"):
            with self.subTest(alias=alias):
                self.assertEqual(["youtube"], agent_server.publish_platforms(f"publish on {alias}"))

        pending = agent_server.build_pending_publish(
            message,
            "The material is ready for YouTube.",
            "I am back! Let us keep going.",
            run_id="youtube-typo-run",
            force_auto_publish=True,
        )

        self.assertIsNotNone(pending)
        self.assertEqual("youtube", pending["platform"])
        self.assertEqual(["youtube"], pending["platforms"])
        self.assertEqual("approval_required", pending["status"])
        self.assertFalse(pending["autoPublish"])
        self.assertNotIn("telegram", pending["platforms"])
        self.assertIn("Community posts", pending["notice"])

    def test_agent_youtube_conclusion_overrides_legacy_telegram_default(self) -> None:
        pending = agent_server.build_pending_publish(
            "Prepare and publish this social post",
            "The copy is prepared for YouTube and needs a video URL.",
            "I am back! Let us keep going.",
            run_id="youtube-context-run",
            force_auto_publish=True,
        )

        self.assertIsNotNone(pending)
        self.assertEqual(["youtube"], pending["platforms"])
        self.assertFalse(pending["autoPublish"])

    def test_social_posting_prompts_teach_agents_the_youtube_publish_contract(self) -> None:
        message = "Upload https://cdn.example.com/launch.mp4 to YouTube."
        assignments = agent_server.social_posting_assignments({}, message)
        combined_tasks = "\n".join(item["task"] for item in assignments)
        coordinator_prompt = agent_server.build_coordinator_decision_prompt(message, [])
        final_prompt = agent_server.build_coordinator_final_prompt(message, [], {}, [])

        self.assertIn("YouTube", coordinator_prompt)
        self.assertIn("Dex", coordinator_prompt)
        self.assertIn("public HTTPS video URL", combined_tasks)
        self.assertIn("upload_youtube_video", combined_tasks)
        self.assertIn("private", combined_tasks)
        self.assertIn("YouTube", final_prompt)
        self.assertIn("approval", final_prompt)

    def test_google_requests_become_explicit_office_action_cards(self) -> None:
        search = agent_server.build_pending_google_action(
            "Search my Gmail for invoices from client@example.com",
            run_id="google-search-1",
        )
        self.assertIsNotNone(search)
        self.assertEqual("search_gmail", search["tool"])
        self.assertFalse(search["requiresApproval"])
        self.assertIn("invoices", search["arguments"]["query"])

        send = agent_server.build_pending_google_action(
            'Send a Gmail email to client@example.com subject: Project update "The draft is ready."',
            run_id="google-send-1",
        )
        self.assertIsNotNone(send)
        self.assertEqual("send_gmail", send["tool"])
        self.assertTrue(send["requiresApproval"])
        self.assertEqual(["client@example.com"], send["arguments"]["to"])

        calendar = agent_server.build_pending_google_action(
            "Create a Google Calendar event subject: Planning 2026-07-14T09:00:00Z 2026-07-14T10:00:00Z",
            run_id="google-calendar-1",
        )
        self.assertIsNotNone(calendar)
        self.assertEqual("create_calendar_event", calendar["tool"])
        self.assertTrue(calendar["requiresApproval"])
        self.assertEqual("2026-07-14T09:00:00Z", calendar["arguments"]["start"])

        sheet = agent_server.build_pending_google_action(
            "Append a row to Google Sheets https://docs.google.com/spreadsheets/d/sheet-id-123/edit range: Leads!A:B",
            run_id="google-sheet-1",
        )
        self.assertIsNotNone(sheet)
        self.assertEqual("append_google_sheet_row", sheet["tool"])
        self.assertTrue(sheet["requiresApproval"])
        self.assertEqual("sheet-id-123", sheet["arguments"]["spreadsheetId"])
        self.assertEqual("Leads!A:B", sheet["arguments"]["range"])

    def test_production_exposes_only_google_read_action_cards(self) -> None:
        with patch.object(agent_server, "IS_PRODUCTION", True):
            write = agent_server.build_pending_google_action(
                "Send Gmail to client@example.com subject: Update",
                run_id="google-write-prod",
            )
            read = agent_server.build_pending_google_action(
                "Search Gmail for the latest invoice",
                run_id="google-read-prod",
            )

        self.assertIsNone(write)
        self.assertEqual("search_gmail", read["tool"])

    def test_youtube_privacy_defaults_to_private_without_an_explicit_visibility_request(self) -> None:
        self.assertEqual("private", agent_server.youtube_privacy_status("Use a public HTTPS video URL."))
        self.assertEqual("unlisted", agent_server.youtube_privacy_status("Upload as unlisted."))
        self.assertEqual("public", agent_server.youtube_privacy_status("privacy: public"))


if __name__ == "__main__":
    unittest.main()
