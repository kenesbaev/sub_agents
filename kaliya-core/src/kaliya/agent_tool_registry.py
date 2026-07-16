from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SENSITIVE_LEVELS = {"send", "publish", "delete", "admin"}


@dataclass(frozen=True)
class ToolDefinition:
    id: str
    name: str
    category: str
    access_level: str
    description: str
    connected_apps: tuple[str, ...] = ()
    requires_approval: bool = False


@dataclass(frozen=True)
class AgentToolProfile:
    agent_id: str
    role: str
    tools: tuple[str, ...]
    can_approve_levels: tuple[str, ...] = ()


TOOLS: dict[str, ToolDefinition] = {
    "assign_task": ToolDefinition(
        "assign_task",
        "Assign task",
        "coordination",
        "write",
        "Route work to the correct specialist agent.",
    ),
    "check_task_status": ToolDefinition(
        "check_task_status",
        "Check task status",
        "coordination",
        "read",
        "Inspect active work, pending approvals, and scheduled actions.",
    ),
    "approve_action": ToolDefinition(
        "approve_action",
        "Approve action",
        "coordination",
        "admin",
        "Approve a sensitive external action before execution.",
        requires_approval=False,
    ),
    "reject_action": ToolDefinition(
        "reject_action",
        "Reject action",
        "coordination",
        "admin",
        "Reject a pending external action.",
        requires_approval=False,
    ),
    "write_activity_log": ToolDefinition(
        "write_activity_log",
        "Write activity log",
        "activity",
        "write",
        "Record agent actions, external calls, and outcomes.",
    ),
    "read_activity_log": ToolDefinition(
        "read_activity_log",
        "Read activity log",
        "activity",
        "read",
        "Read recent workspace actions and publish results.",
    ),
    "get_connected_apps_status": ToolDefinition(
        "get_connected_apps_status",
        "Connected apps status",
        "integrations",
        "read",
        "Check which apps are connected and what capabilities are available.",
    ),
    "get_agent_capabilities": ToolDefinition(
        "get_agent_capabilities",
        "Agent capabilities",
        "coordination",
        "read",
        "Inspect which tools each agent is allowed to use.",
    ),
    "schedule_task": ToolDefinition(
        "schedule_task",
        "Schedule task",
        "scheduler",
        "write",
        "Create a future task or publish job.",
    ),
    "cancel_scheduled_task": ToolDefinition(
        "cancel_scheduled_task",
        "Cancel scheduled task",
        "scheduler",
        "delete",
        "Cancel a scheduled task or publish job.",
        requires_approval=True,
    ),
    "create_post": ToolDefinition(
        "create_post",
        "Create post",
        "marketing",
        "draft",
        "Draft a social post for review.",
    ),
    "rewrite_post": ToolDefinition(
        "rewrite_post",
        "Rewrite post",
        "marketing",
        "draft",
        "Rewrite a post for a new audience, offer, or platform.",
    ),
    "create_caption": ToolDefinition(
        "create_caption",
        "Create caption",
        "marketing",
        "draft",
        "Create a short caption for an image or video.",
    ),
    "create_hashtags": ToolDefinition(
        "create_hashtags",
        "Create hashtags",
        "marketing",
        "draft",
        "Create platform-appropriate hashtags.",
    ),
    "create_image_prompt": ToolDefinition(
        "create_image_prompt",
        "Create image prompt",
        "creative",
        "draft",
        "Create image generation prompts and visual briefs.",
    ),
    "schedule_social_post": ToolDefinition(
        "schedule_social_post",
        "Schedule social post",
        "scheduler",
        "write",
        "Schedule a social post for future publishing.",
        connected_apps=("telegram", "instagram", "facebook", "linkedin", "youtube"),
        requires_approval=True,
    ),
    "publish_social_post": ToolDefinition(
        "publish_social_post",
        "Publish social post",
        "publishing",
        "publish",
        "Publish approved text, photo, video, document, or album to connected social apps.",
        connected_apps=("telegram", "instagram", "facebook", "linkedin", "youtube"),
        requires_approval=True,
    ),
    "upload_youtube_video": ToolDefinition(
        "upload_youtube_video",
        "Upload YouTube video",
        "publishing",
        "publish",
        "Upload an approved public video URL to a connected YouTube channel with title, description, and privacy settings.",
        connected_apps=("youtube",),
        requires_approval=True,
    ),
    "get_social_comments": ToolDefinition(
        "get_social_comments",
        "Get social comments",
        "social_inbox",
        "read",
        "Read comments and replies from connected social apps.",
        connected_apps=("instagram", "facebook", "linkedin", "youtube"),
    ),
    "reply_to_comment": ToolDefinition(
        "reply_to_comment",
        "Reply to comment",
        "social_inbox",
        "send",
        "Reply to a public comment after approval.",
        connected_apps=("instagram", "facebook", "linkedin", "youtube"),
        requires_approval=True,
    ),
    "get_social_analytics": ToolDefinition(
        "get_social_analytics",
        "Get social analytics",
        "analytics",
        "read",
        "Read post and channel analytics.",
        connected_apps=("instagram", "facebook", "linkedin", "youtube"),
    ),
    "search_gmail": ToolDefinition(
        "search_gmail",
        "Search Gmail",
        "gmail",
        "read",
        "Search email threads.",
        connected_apps=("google", "gmail"),
    ),
    "read_gmail_thread": ToolDefinition(
        "read_gmail_thread",
        "Read Gmail thread",
        "gmail",
        "read",
        "Read a selected email thread.",
        connected_apps=("google", "gmail"),
    ),
    "create_gmail_draft": ToolDefinition(
        "create_gmail_draft",
        "Create Gmail draft",
        "gmail",
        "draft",
        "Create an email draft for review.",
        connected_apps=("google", "gmail"),
        requires_approval=True,
    ),
    "send_gmail": ToolDefinition(
        "send_gmail",
        "Send Gmail",
        "gmail",
        "send",
        "Send an approved email.",
        connected_apps=("google", "gmail"),
        requires_approval=True,
    ),
    "reply_gmail": ToolDefinition(
        "reply_gmail",
        "Reply Gmail",
        "gmail",
        "send",
        "Reply to an email thread after approval.",
        connected_apps=("google", "gmail"),
        requires_approval=True,
    ),
    "create_calendar_event": ToolDefinition(
        "create_calendar_event",
        "Create calendar event",
        "calendar",
        "write",
        "Create a meeting or reminder.",
        connected_apps=("google", "calendar"),
        requires_approval=True,
    ),
    "reschedule_calendar_event": ToolDefinition(
        "reschedule_calendar_event",
        "Reschedule calendar event",
        "calendar",
        "write",
        "Move a calendar event.",
        connected_apps=("google", "calendar"),
        requires_approval=True,
    ),
    "delete_calendar_event": ToolDefinition(
        "delete_calendar_event",
        "Delete calendar event",
        "calendar",
        "delete",
        "Delete a calendar event.",
        connected_apps=("google", "calendar"),
        requires_approval=True,
    ),
    "find_free_time": ToolDefinition(
        "find_free_time",
        "Find free time",
        "calendar",
        "read",
        "Find available meeting windows.",
        connected_apps=("google", "calendar"),
    ),
    "list_calendar_events": ToolDefinition(
        "list_calendar_events",
        "List calendar events",
        "calendar",
        "read",
        "Read upcoming events from a connected Google Calendar.",
        connected_apps=("google", "calendar"),
    ),
    "search_drive_files": ToolDefinition(
        "search_drive_files",
        "Search Drive files",
        "drive",
        "read",
        "Search Google Drive files.",
        connected_apps=("google", "drive"),
    ),
    "read_drive_file": ToolDefinition(
        "read_drive_file",
        "Read Drive file",
        "drive",
        "read",
        "Read supported Drive files for context.",
        connected_apps=("google", "drive"),
    ),
    "upload_document": ToolDefinition(
        "upload_document",
        "Upload document",
        "drive",
        "write",
        "Upload a document to Drive.",
        connected_apps=("google", "drive"),
        requires_approval=True,
    ),
    "create_folder": ToolDefinition(
        "create_folder",
        "Create folder",
        "drive",
        "write",
        "Create a Drive folder.",
        connected_apps=("google", "drive"),
    ),
    "create_google_doc": ToolDefinition(
        "create_google_doc",
        "Create Google Doc",
        "docs",
        "write",
        "Create a Google Doc.",
        connected_apps=("google", "docs"),
    ),
    "edit_google_doc": ToolDefinition(
        "edit_google_doc",
        "Edit Google Doc",
        "docs",
        "write",
        "Edit an existing Google Doc.",
        connected_apps=("google", "docs"),
        requires_approval=True,
    ),
    "read_google_sheet": ToolDefinition(
        "read_google_sheet",
        "Read Google Sheet",
        "sheets",
        "read",
        "Read rows from Google Sheets.",
        connected_apps=("google", "sheets"),
    ),
    "append_google_sheet_row": ToolDefinition(
        "append_google_sheet_row",
        "Append Google Sheet row",
        "sheets",
        "write",
        "Add a row to a Google Sheet.",
        connected_apps=("google", "sheets"),
        requires_approval=True,
    ),
    "update_google_sheet_row": ToolDefinition(
        "update_google_sheet_row",
        "Update Google Sheet row",
        "sheets",
        "write",
        "Update an existing row in Google Sheets.",
        connected_apps=("google", "sheets"),
        requires_approval=True,
    ),
    "create_lead": ToolDefinition(
        "create_lead",
        "Create lead",
        "crm",
        "write",
        "Create a CRM lead record.",
        connected_apps=("google", "sheets"),
    ),
    "update_lead": ToolDefinition(
        "update_lead",
        "Update lead",
        "crm",
        "write",
        "Update a CRM lead record.",
        connected_apps=("google", "sheets"),
        requires_approval=True,
    ),
    "create_follow_up": ToolDefinition(
        "create_follow_up",
        "Create follow-up",
        "sales",
        "draft",
        "Prepare follow-up text, next step, and timing.",
    ),
    "reply_instagram_direct": ToolDefinition(
        "reply_instagram_direct",
        "Reply Instagram Direct",
        "social_inbox",
        "send",
        "Reply to an Instagram Direct message after approval.",
        connected_apps=("instagram",),
        requires_approval=True,
    ),
    "reply_facebook_messenger": ToolDefinition(
        "reply_facebook_messenger",
        "Reply Facebook Messenger",
        "social_inbox",
        "send",
        "Reply to a Messenger thread after approval.",
        connected_apps=("facebook",),
        requires_approval=True,
    ),
    "web_search": ToolDefinition(
        "web_search",
        "Web search",
        "research",
        "read",
        "Research public web information.",
    ),
    "summarize_document": ToolDefinition(
        "summarize_document",
        "Summarize document",
        "research",
        "read",
        "Summarize documents and extract insights.",
    ),
    "extract_insights": ToolDefinition(
        "extract_insights",
        "Extract insights",
        "research",
        "read",
        "Extract actionable findings from docs, sheets, and conversations.",
    ),
    "build_knowledge_base": ToolDefinition(
        "build_knowledge_base",
        "Build knowledge base",
        "research",
        "write",
        "Use approved documents as reusable workspace knowledge.",
    ),
}


AGENT_TOOL_PROFILES: dict[str, AgentToolProfile] = {
    "all": AgentToolProfile(
        "all",
        "Team route. Uses Atlas first and delegates tools to specialist agents.",
        ("get_connected_apps_status", "get_agent_capabilities", "read_activity_log"),
    ),
    "coordinator": AgentToolProfile(
        "coordinator",
        "Coordinator. Routes work, checks status, logs actions, and approves sensitive operations.",
        (
            "assign_task",
            "check_task_status",
            "approve_action",
            "reject_action",
            "write_activity_log",
            "read_activity_log",
            "get_connected_apps_status",
            "get_agent_capabilities",
            "schedule_task",
            "cancel_scheduled_task",
        ),
        can_approve_levels=("send", "publish", "delete", "admin", "write"),
    ),
    "scout": AgentToolProfile(
        "scout",
        "Marketing and research. Creates content, captions, creative briefs, and read-only insights.",
        (
            "web_search",
            "create_post",
            "rewrite_post",
            "create_caption",
            "create_hashtags",
            "create_image_prompt",
            "schedule_social_post",
            "get_social_comments",
            "get_social_analytics",
            "search_drive_files",
            "read_drive_file",
            "summarize_document",
            "extract_insights",
            "build_knowledge_base",
        ),
    ),
    "mika": AgentToolProfile(
        "mika",
        "Sales and client communication. Works with email drafts, meetings, leads, CRM, and follow-up.",
        (
            "search_gmail",
            "read_gmail_thread",
            "create_gmail_draft",
            "send_gmail",
            "reply_gmail",
            "list_calendar_events",
            "find_free_time",
            "create_calendar_event",
            "reschedule_calendar_event",
            "read_google_sheet",
            "append_google_sheet_row",
            "update_google_sheet_row",
            "create_lead",
            "update_lead",
            "create_follow_up",
        ),
    ),
    "dev": AgentToolProfile(
        "dev",
        "Publisher, operations, and growth engineer. Executes approved publishing and operational writes.",
        (
            "publish_social_post",
            "upload_youtube_video",
            "schedule_social_post",
            "get_social_analytics",
            "read_google_sheet",
            "append_google_sheet_row",
            "update_google_sheet_row",
            "create_google_doc",
            "edit_google_doc",
            "upload_document",
            "create_folder",
            "write_activity_log",
            "read_activity_log",
        ),
    ),
    "nova": AgentToolProfile(
        "nova",
        "Support and inbox. Handles support replies, comments, direct messages, and knowledge lookup.",
        (
            "search_gmail",
            "read_gmail_thread",
            "create_gmail_draft",
            "reply_gmail",
            "get_social_comments",
            "reply_to_comment",
            "reply_instagram_direct",
            "reply_facebook_messenger",
            "search_drive_files",
            "read_drive_file",
            "summarize_document",
            "create_follow_up",
        ),
    ),
}


def get_agent_tools(agent_id: str) -> list[ToolDefinition]:
    profile = AGENT_TOOL_PROFILES.get(agent_id, AGENT_TOOL_PROFILES["coordinator"])
    return [TOOLS[tool_id] for tool_id in profile.tools if tool_id in TOOLS]


def can_agent_use_tool(agent_id: str, tool_id: str) -> bool:
    profile = AGENT_TOOL_PROFILES.get(agent_id)
    return bool(profile and tool_id in profile.tools and tool_id in TOOLS)


def tool_requires_approval(tool_id: str) -> bool:
    tool = TOOLS.get(tool_id)
    if not tool:
        return True
    return tool.requires_approval or tool.access_level in SENSITIVE_LEVELS


def agent_capabilities_payload(agent_id: str) -> dict[str, Any]:
    profile = AGENT_TOOL_PROFILES.get(agent_id, AGENT_TOOL_PROFILES["coordinator"])
    tools = get_agent_tools(agent_id)
    return {
        "agentId": profile.agent_id,
        "role": profile.role,
        "canApproveLevels": list(profile.can_approve_levels),
        "tools": [
            {
                "id": tool.id,
                "name": tool.name,
                "category": tool.category,
                "accessLevel": tool.access_level,
                "connectedApps": list(tool.connected_apps),
                "requiresApproval": tool.requires_approval or tool.access_level in SENSITIVE_LEVELS,
                "description": tool.description,
            }
            for tool in tools
        ],
    }


def agent_tool_prompt(agent_id: str) -> str:
    profile = AGENT_TOOL_PROFILES.get(agent_id, AGENT_TOOL_PROFILES["coordinator"])
    tools = get_agent_tools(agent_id)
    lines = [
        "Agent tool permissions:",
        f"- Role: {profile.role}",
        "- Use only the tools listed below. If a needed tool is not listed, ask Atlas to delegate to the correct agent.",
        "- Read/draft tools may be prepared directly. External send/publish/delete/admin actions require explicit user approval or Atlas approval.",
    ]
    if profile.can_approve_levels:
        lines.append(f"- This agent can approve levels: {', '.join(profile.can_approve_levels)}.")
    lines.append("- Allowed tools:")
    for tool in tools:
        approval = "approval required" if tool.requires_approval or tool.access_level in SENSITIVE_LEVELS else "no approval for draft/read"
        apps = f" apps={','.join(tool.connected_apps)}" if tool.connected_apps else ""
        lines.append(f"  - {tool.id} [{tool.access_level}; {approval}{apps}]: {tool.description}")
    return "\n".join(lines)


def get_agent_capabilities() -> dict[str, Any]:
    return {
        "agents": {
            agent_id: agent_capabilities_payload(agent_id)
            for agent_id in AGENT_TOOL_PROFILES
        },
        "approvalRequiredLevels": sorted(SENSITIVE_LEVELS),
    }
