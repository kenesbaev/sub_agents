from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DefaultAgentDefinition:
    slug: str
    name: str
    role: str
    avatar: str | None = None
    accent: str | None = None


@dataclass(frozen=True)
class DefaultTeamDefinition:
    slug: str
    name: str
    category: str
    description: str
    agents_count: int
    output: str
    tags: tuple[str, ...]
    icon: str
    roster: tuple[DefaultAgentDefinition, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


DEFAULT_TEAM_DEFINITIONS: tuple[DefaultTeamDefinition, ...] = (
    DefaultTeamDefinition(
        slug="social-posting-team",
        name="Social Posting Team",
        category="Social",
        description="Team for auto-posting: prepares ideas, captions, visual briefs, and approved posts through Connected Apps.",
        agents_count=5,
        output="Publish-ready caption/video metadata + Telegram/Instagram/YouTube publish status",
        tags=("Marketing", "Instagram", "Telegram", "YouTube"),
        icon="Share2",
        roster=(
            DefaultAgentDefinition("atlas", "Atlas", "Coordinator", "/images/agents/coordinator.png", "#4F5BD5"),
            DefaultAgentDefinition("scout", "Scout", "Research", "/images/agents/scout.png", "#0EA5E9"),
            DefaultAgentDefinition("mira", "Mira", "Copy + creative", "/images/member-woman.png", "#16A3A3"),
            DefaultAgentDefinition("dex", "Dex", "Publisher", "/images/agents/dev.png", "#13A56F"),
            DefaultAgentDefinition("echo", "Echo", "Analytics", "/images/agents/nova.png", "#C98908"),
        ),
        metadata={
            "source": "ready",
            "frontend_source_id": "social-posting-team",
            "workflow": (
                "Atlas accepts the task and selects Telegram, Instagram, YouTube, or a supported combination.",
                "Scout researches the topic, audience, angle, and platform-specific format.",
                "Mira writes the caption or YouTube title and description.",
                "Dex checks Connected Apps and publishes approved content; YouTube requires a public HTTPS video URL and separate approval.",
                "Echo records the confirmed publish status, YouTube video URL/privacy, and safe errors for later review.",
            ),
        },
    ),
    DefaultTeamDefinition(
        slug="business-ai-team",
        name="Business AI Team",
        category="Business",
        description="Team for strategy, growth, CRM, sales, and analytics when a founder needs a clear business plan.",
        agents_count=5,
        output="Strategy + CRM pipeline + sales scripts + KPI dashboard",
        tags=("Business", "Strategy", "CRM"),
        icon="BriefcaseBusiness",
        roster=(
            DefaultAgentDefinition("adam", "Adam", "Strategist", "/images/member-man.png", "#635BFF"),
            DefaultAgentDefinition("mira", "Mira", "Ideas and growth", "/images/member-woman.png", "#16A3A3"),
            DefaultAgentDefinition("leo", "Leo", "Sales", "/images/member-man.png", "#2563EB"),
            DefaultAgentDefinition("nora", "Nora", "CRM", None, "#8B5CF6"),
            DefaultAgentDefinition("kai", "Kai", "Analytics", None, "#0EA5E9"),
        ),
        metadata={
            "source": "ready",
            "frontend_source_id": "business-ai-team",
            "workflow": (
                "Coordinator gathers context and records the goal.",
                "Adam prepares strategy, positioning, and action priorities.",
                "Mira proposes growth, marketing, and product ideas.",
                "Nora builds CRM stages and follow-up rules.",
                "Leo prepares offers, scripts, and first messages.",
                "Kai reviews metrics and prepares a KPI report.",
            ),
        },
    ),
    DefaultTeamDefinition(
        slug="founders-cos",
        name="Founder's COS",
        category="Operations",
        description="Personal operations assistant for founder priorities, decisions, investor updates, and weekly briefs.",
        agents_count=1,
        output="Approve cards + weekly brief + inbox-log",
        tags=("Founder", "Operations", "Digest"),
        icon="Rocket",
        roster=(
            DefaultAgentDefinition("reese", "Reese", "Operations Manager", "/images/member-man.png", "#F43F5E"),
        ),
        metadata={
            "source": "ready",
            "frontend_source_id": "founders-cos",
            "workflow": (
                "Coordinator gathers weekly intake and important decisions.",
                "Reese reviews KPI, runway, scheduling changes, and priority risks.",
                "Coordinator writes the weekly executive brief.",
                "Coordinator prepares approval cards and follow-up items.",
            ),
        },
    ),
    DefaultTeamDefinition(
        slug="marketing-team",
        name="Marketing Team",
        category="Growth",
        description="Marketing team for content calendars, brand-voice drafts, campaigns, and mention replies.",
        agents_count=4,
        output="Content calendar + ready drafts + reply log",
        tags=("Marketing", "Instagram", "Content"),
        icon="BriefcaseBusiness",
        roster=(
            DefaultAgentDefinition("mika", "Mika", "Content", "/images/member-woman.png", "#EC4899"),
            DefaultAgentDefinition("marcus", "Marcus", "Copywriting", None, "#F59E0B"),
            DefaultAgentDefinition("scout", "Scout", "Social media", "/images/member-man.png", "#0EA5E9"),
            DefaultAgentDefinition("hayden", "Hayden", "Community", None, "#10B981"),
        ),
        metadata={
            "source": "ready",
            "frontend_source_id": "marketing-team",
            "workflow": (
                "Mika assembles the weekly content calendar.",
                "Marcus writes copy and visual briefs.",
                "Scout reviews reactions, reach, and useful signals.",
                "Hayden prepares replies for mentions and comments.",
            ),
        },
    ),
    DefaultTeamDefinition(
        slug="sales-team",
        name="Sales Team",
        category="Sales",
        description="Inbound sales team for fast lead replies, qualification, offers, and CRM updates.",
        agents_count=4,
        output="Qualified lead list + reply drafts + CRM notes",
        tags=("Sales", "Leads", "CRM"),
        icon="UsersRound",
        roster=(
            DefaultAgentDefinition("leo", "Leo", "Sales", "/images/member-man.png", "#2563EB"),
            DefaultAgentDefinition("nora", "Nora", "CRM", None, "#8B5CF6"),
            DefaultAgentDefinition("adam", "Adam", "Offers", "/images/member-man.png", "#635BFF"),
        ),
        metadata={
            "source": "ready",
            "frontend_source_id": "sales-team",
            "workflow": (
                "Leo evaluates new leads and buying signals.",
                "Nora updates CRM stage and follow-up.",
                "Adam prepares offer and deal arguments.",
            ),
        },
    ),
    DefaultTeamDefinition(
        slug="support-team",
        name="Support Team",
        category="Support",
        description="Support team that triages tickets, drafts clear replies, and finds recurring issues.",
        agents_count=5,
        output="Ticket replies + issue report + frequent problem list",
        tags=("Support", "Tickets", "QA"),
        icon="LifeBuoy",
        roster=(
            DefaultAgentDefinition("sofia", "Sofia", "Clients", "/images/member-woman.png", "#EC4899"),
            DefaultAgentDefinition("kai", "Kai", "Reports", None, "#0EA5E9"),
            DefaultAgentDefinition("mira", "Mira", "Replies", "/images/member-woman.png", "#16A3A3"),
        ),
        metadata={
            "source": "ready",
            "frontend_source_id": "support-team",
            "workflow": (
                "Sofia sorts tickets by urgency.",
                "Mira writes replies from product context.",
                "Kai collects recurring problems into a report.",
            ),
        },
    ),
)
