from __future__ import annotations

import asyncio
import json
import sys
import tempfile
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


class AgentFoundationTest(unittest.TestCase):
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

    def test_link_reader_blocks_private_links(self) -> None:
        summary = asyncio.run(
            fetch_link_summary(
                "http://127.0.0.1:9999/private",
                timeout_seconds=1,
                max_bytes=1024,
            )
        )

        self.assertIn("blocked", summary.error.lower())

    def test_csv_upload_builds_context_and_saves_dataset(self) -> None:
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
            try:
                tool_context = context.tool_context
                self.assertIn("CSV context", tool_context)
                self.assertIn("Columns (2): name, revenue", tool_context)
                self.assertTrue((data_dir / "tables" / "local" / "sales.csv").exists())
            finally:
                context.cleanup()

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

        def fake_urlopen(request: object) -> FakeResponse:
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        with patch.dict("agent_server.os.environ", {"OPENROUTER_API_KEY": "test-key"}, clear=False):
            with patch("agent_server.urllib.request.urlopen", side_effect=fake_urlopen):
                self.assertEqual(
                    "ok",
                    agent_server.run_openrouter(
                        "hello",
                        agent_id="coordinator",
                        image_paths=[],
                        search_enabled=False,
                    ),
                )

        self.assertEqual(
            agent_server.OPENROUTER_MAX_TOKENS,
            captured["payload"]["max_tokens"],
        )

    def test_run_ai_preserves_agent_run_cancelled(self) -> None:
        with patch("agent_server.run_openrouter", side_effect=RuntimeError("primary failed")):
            with patch("agent_server.run_codex", side_effect=agent_server.AgentRunCancelled("cancel-me")):
                with self.assertRaises(agent_server.AgentRunCancelled):
                    agent_server.run_ai("hello", run_id="cancel-me")

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

    def test_youtube_privacy_defaults_to_private_without_an_explicit_visibility_request(self) -> None:
        self.assertEqual("private", agent_server.youtube_privacy_status("Use a public HTTPS video URL."))
        self.assertEqual("unlisted", agent_server.youtube_privacy_status("Upload as unlisted."))
        self.assertEqual("public", agent_server.youtube_privacy_status("privacy: public"))


if __name__ == "__main__":
    unittest.main()
