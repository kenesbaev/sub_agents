from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KALIYA_CORE_SRC = ROOT / "kaliya-core" / "src"
BACKEND_SRC = ROOT / "backend"
for source in (KALIYA_CORE_SRC, BACKEND_SRC):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from app.core_domain.seeds import DEFAULT_TEAM_DEFINITIONS  # noqa: E402
from kaliya.agent_tool_registry import (  # noqa: E402
    SENSITIVE_LEVELS,
    can_agent_use_tool,
    get_agent_tools,
    tool_requires_approval,
)


YOUTUBE_GROWTH_ROLES = (
    "youtube-trend-scout",
    "youtube-competitor-analyst",
    "youtube-video-analyst",
    "youtube-content-strategist",
    "youtube-creative-director",
    "youtube-growth-analyst",
    "youtube-publisher",
)


class YouTubeGrowthAgentCoreTest(unittest.TestCase):
    def test_seeded_team_keeps_atlas_and_seven_internal_roles(self) -> None:
        team = next(item for item in DEFAULT_TEAM_DEFINITIONS if item.slug == "youtube-growth-team")

        self.assertEqual(8, team.agents_count)
        self.assertEqual("atlas", team.roster[0].slug)
        self.assertEqual(YOUTUBE_GROWTH_ROLES, tuple(item.slug for item in team.roster[1:]))
        self.assertIn("YouTube", team.tags)
        self.assertTrue(any("explicit user approval" in step for step in team.metadata["workflow"]))
        self.assertTrue(any("Do not download" in rule for rule in team.metadata["guardrails"]))

    def test_growth_roles_have_no_sensitive_tools_except_publisher(self) -> None:
        for role in YOUTUBE_GROWTH_ROLES[:-1]:
            with self.subTest(role=role):
                tools = get_agent_tools(role)
                self.assertTrue(tools)
                self.assertTrue(all(tool.access_level not in SENSITIVE_LEVELS for tool in tools))
                self.assertTrue(all(not tool_requires_approval(tool.id) for tool in tools))
                self.assertFalse(can_agent_use_tool(role, "upload_youtube_video"))

        publisher_tools = get_agent_tools("youtube-publisher")
        sensitive_tools = [tool.id for tool in publisher_tools if tool_requires_approval(tool.id)]
        self.assertEqual(["upload_youtube_video"], sensitive_tools)
        self.assertTrue(can_agent_use_tool("youtube-publisher", "upload_youtube_video"))

    def test_growth_capabilities_are_role_scoped(self) -> None:
        expected_tool = {
            "youtube-trend-scout": "youtube_search_trends",
            "youtube-competitor-analyst": "youtube_analyze_competitors",
            "youtube-video-analyst": "youtube_analyze_video",
            "youtube-content-strategist": "youtube_create_content_plan",
            "youtube-creative-director": "youtube_create_creative_package",
            "youtube-growth-analyst": "youtube_analyze_growth",
        }
        for role, tool_id in expected_tool.items():
            with self.subTest(role=role):
                self.assertEqual([tool_id], [tool.id for tool in get_agent_tools(role)])
                self.assertTrue(can_agent_use_tool(role, tool_id))


if __name__ == "__main__":
    unittest.main()
