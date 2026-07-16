from __future__ import annotations

import importlib.util
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "local_codex_agent.py"
SPEC = importlib.util.spec_from_file_location("local_codex_agent", MODULE_PATH)
assert SPEC and SPEC.loader
local_codex_agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(local_codex_agent)


class LocalCodexAgentTest(unittest.TestCase):
    def test_login_check_requires_chatgpt_status(self) -> None:
        runner = Mock(
            return_value=SimpleNamespace(
                returncode=0,
                stdout="",
                stderr="Logged in using ChatGPT\n",
            )
        )

        self.assertTrue(
            local_codex_agent.has_chatgpt_codex_login(
                which=lambda _name: "codex",
                runner=runner,
            )
        )

        command, = runner.call_args.args
        self.assertEqual(["codex", "login", "status"], command)
        self.assertEqual(str(ROOT), runner.call_args.kwargs["cwd"])
        self.assertEqual(subprocess.DEVNULL, runner.call_args.kwargs["stdin"])

    def test_login_check_rejects_missing_or_non_chatgpt_login(self) -> None:
        self.assertFalse(
            local_codex_agent.has_chatgpt_codex_login(
                which=lambda _name: None,
            )
        )
        self.assertFalse(
            local_codex_agent.has_chatgpt_codex_login(
                which=lambda _name: "codex",
                runner=lambda *_args, **_kwargs: SimpleNamespace(
                    returncode=0,
                    stdout="Logged in using API key\n",
                    stderr="",
                ),
            )
        )

    def test_run_task_uses_workspace_root_and_workspace_write(self) -> None:
        calls: dict[str, object] = {}

        class FakeConfig:
            def __init__(self, **kwargs: object) -> None:
                calls["config"] = kwargs

        class FakeThread:
            def run(self, task: str, **kwargs: object) -> SimpleNamespace:
                calls["run"] = (task, kwargs)
                return SimpleNamespace(final_response="done")

        class FakeCodex:
            def __init__(self, _config: FakeConfig) -> None:
                pass

            def __enter__(self) -> "FakeCodex":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def thread_start(self, **kwargs: object) -> FakeThread:
                calls["thread_start"] = kwargs
                return FakeThread()

        self.assertEqual(
            "done",
            local_codex_agent.run_task(
                "Inspect the project",
                codex_type=FakeCodex,
                config_type=FakeConfig,
                workspace_write="workspace-write",
            ),
        )

        expected_root = str(ROOT)
        self.assertEqual(
            {
                "cwd": expected_root,
                "config_overrides": (
                    'model="gpt-5.4"',
                    'model_reasoning_effort="xhigh"',
                ),
            },
            calls["config"],
        )
        self.assertEqual(expected_root, calls["thread_start"]["cwd"])
        self.assertEqual("gpt-5.4", calls["thread_start"]["model"])
        self.assertEqual(
            "workspace-write",
            calls["thread_start"]["sandbox"],
        )
        self.assertEqual(
            (
                "Inspect the project",
                {
                    "cwd": expected_root,
                    "model": "gpt-5.4",
                    "sandbox": "workspace-write",
                },
            ),
            calls["run"],
        )

    def test_agent_instruction_protects_credential_store(self) -> None:
        self.assertIn("~/.codex/auth.json", local_codex_agent.LOCAL_AGENT_INSTRUCTIONS)
        self.assertIn("Never disclose secrets", local_codex_agent.LOCAL_AGENT_INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
