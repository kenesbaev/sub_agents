from __future__ import annotations

import asyncio
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

        class FakeProcess:
            returncode = 0

            def communicate(self, input: str | None, timeout: float) -> tuple[str, str]:
                self.input = input
                return "ok", ""

        def fake_popen(*_args: object, **kwargs: object) -> FakeProcess:
            popen_kwargs.update(kwargs)
            return FakeProcess()

        with patch("agent_server.shutil.which", return_value="codex"):
            with patch("agent_server.subprocess.Popen", side_effect=fake_popen):
                self.assertEqual("ok", agent_server.run_codex("Я лечу в Китай 🚀", agent_id="mika"))

        self.assertEqual("utf-8", popen_kwargs.get("encoding"))
        self.assertEqual("replace", popen_kwargs.get("errors"))

    def test_run_ai_preserves_agent_run_cancelled(self) -> None:
        with patch("agent_server.run_openrouter", side_effect=RuntimeError("primary failed")):
            with patch("agent_server.run_codex", side_effect=agent_server.AgentRunCancelled("cancel-me")):
                with self.assertRaises(agent_server.AgentRunCancelled):
                    agent_server.run_ai("hello", run_id="cancel-me")


if __name__ == "__main__":
    unittest.main()
