"""Run a local Codex SDK agent in the Rebly AI workspace.

This is deliberately a local CLI tool.  It exposes no HTTP endpoint and never
reads, copies, or prints the Codex credential store.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# The official Python SDK is currently beta and ships a pinned Codex runtime.
# These compatible values keep the local tool independent from newer settings in
# the user's desktop Codex configuration while still using the ChatGPT login.
SDK_MODEL = "gpt-5.4"
SDK_REASONING_EFFORT = "xhigh"
LOCAL_AGENT_INSTRUCTIONS = """You are a local developer agent for Rebly AI.
Work only within the provided project workspace. Never access, copy, print, or
modify ~/.codex/auth.json or any authentication store. Never disclose secrets,
tokens, passwords, or API keys found in files, commands, or tool output; redact
them instead. Complete the user's task and summarize the result concisely.
"""


def has_chatgpt_codex_login(
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., Any] = subprocess.run,
) -> bool:
    """Return whether the local Codex CLI is authenticated with ChatGPT.

    The check deliberately invokes only ``codex login status``. It does not
    inspect the credential files that Codex manages internally.
    """

    codex = which("codex")
    if not codex:
        return False

    try:
        completed = runner(
            [codex, "login", "status"],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False

    # Codex Desktop on Windows writes this short status line to stderr.
    status = f"{completed.stdout or ''}\n{completed.stderr or ''}".lower()
    return completed.returncode == 0 and "chatgpt" in status


def run_task(
    task: str,
    *,
    codex_type: Any,
    config_type: Any,
    workspace_write: Any,
) -> str:
    """Run one task through the official SDK with root-only write access."""

    root = str(PROJECT_ROOT)
    config = config_type(
        cwd=root,
        config_overrides=(
            f'model="{SDK_MODEL}"',
            f'model_reasoning_effort="{SDK_REASONING_EFFORT}"',
        ),
    )
    with codex_type(config) as codex:
        thread = codex.thread_start(
            cwd=root,
            model=SDK_MODEL,
            sandbox=workspace_write,
            developer_instructions=LOCAL_AGENT_INSTRUCTIONS,
        )
        result = thread.run(
            task,
            cwd=root,
            model=SDK_MODEL,
            sandbox=workspace_write,
        )

    return result.final_response or "Codex completed without a final text response."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a local Codex agent in the Rebly AI project root.",
    )
    parser.add_argument(
        "task",
        nargs="+",
        help="Task for Codex. Put the task in quotes when it contains spaces.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    task = " ".join(args.task).strip()

    if not has_chatgpt_codex_login():
        print(
            "Codex needs an active ChatGPT login. Run: codex login",
            file=sys.stderr,
        )
        return 2

    try:
        from openai_codex import Codex, CodexConfig, Sandbox
    except ImportError:
        print(
            "Missing local dependency. Run: "
            "backend\\.venv\\Scripts\\python.exe -m pip install -r "
            "tools\\requirements-local-codex.txt",
            file=sys.stderr,
        )
        return 3

    try:
        response = run_task(
            task,
            codex_type=Codex,
            config_type=CodexConfig,
            workspace_write=Sandbox.workspace_write,
        )
    except Exception as error:  # SDK errors can include sensitive provider detail.
        print(
            f"Local Codex agent did not complete ({type(error).__name__}).",
            file=sys.stderr,
        )
        return 1

    print(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
