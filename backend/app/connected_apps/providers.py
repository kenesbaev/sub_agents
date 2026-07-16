from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode


@dataclass(frozen=True)
class CapabilityDefinition:
    key: str
    name: str
    description: str
    access_level: str = "read"
    scope: str = ""


@dataclass(frozen=True)
class ProviderDefinition:
    key: str
    name: str
    auth_type: str
    logo: str
    docs_url: str
    capabilities: tuple[CapabilityDefinition, ...]

    @property
    def scopes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(cap.scope for cap in self.capabilities if cap.scope))


class IntegrationProvider(Protocol):
    key: str

    def get_connect_url(self, *, state: str) -> str:
        ...

    async def handle_callback(self, *, code: str, state: str) -> dict:
        ...

    async def refresh_token(self, *, refresh_token: str) -> dict:
        ...

    def disconnect(self) -> None:
        ...

    def get_status(self) -> dict:
        ...

    def list_capabilities(self) -> list[CapabilityDefinition]:
        ...


class OAuthUrlBuilder:
    def __init__(
        self,
        *,
        auth_uri: str,
        client_id: str,
        redirect_uri: str,
        scopes: tuple[str, ...],
        extra_params: dict[str, str] | None = None,
    ) -> None:
        self.auth_uri = auth_uri
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.extra_params = extra_params or {}

    def get_connect_url(self, *, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "state": state,
            **self.extra_params,
        }
        return f"{self.auth_uri}?{urlencode(params)}"


GOOGLE_CAPABILITIES = (
    CapabilityDefinition("gmail.read", "Gmail Read", "Read selected Gmail messages and threads.", "read", "https://www.googleapis.com/auth/gmail.readonly"),
    CapabilityDefinition("gmail.search", "Gmail Search", "Search Gmail messages.", "read", "https://www.googleapis.com/auth/gmail.readonly"),
    CapabilityDefinition("gmail.draft", "Gmail Draft", "Create Gmail drafts for approval.", "draft", "https://www.googleapis.com/auth/gmail.compose"),
    CapabilityDefinition("gmail.send", "Gmail Send", "Send approved Gmail messages.", "send", "https://www.googleapis.com/auth/gmail.send"),
    CapabilityDefinition("gmail.modify", "Gmail Modify", "Mark, archive, label, and reply to Gmail threads.", "write", "https://www.googleapis.com/auth/gmail.modify"),
    CapabilityDefinition("calendar.read", "Calendar Read", "List events and inspect availability.", "read", "https://www.googleapis.com/auth/calendar.readonly"),
    CapabilityDefinition("calendar.write", "Calendar Events", "Create, move, and delete events.", "write", "https://www.googleapis.com/auth/calendar.events"),
    CapabilityDefinition("calendar.freebusy", "Calendar Freebusy", "Find free meeting time.", "read", "https://www.googleapis.com/auth/calendar.freebusy"),
    CapabilityDefinition("drive.read", "Drive Read", "Search and read Drive files.", "read", "https://www.googleapis.com/auth/drive.readonly"),
    CapabilityDefinition("drive.write", "Drive Upload", "Upload files and create folders.", "write", "https://www.googleapis.com/auth/drive.file"),
    CapabilityDefinition("docs.write", "Google Docs", "Create and edit Google Docs.", "write", "https://www.googleapis.com/auth/documents"),
    CapabilityDefinition("sheets.write", "Google Sheets", "Read and update Google Sheets CRM data.", "write", "https://www.googleapis.com/auth/spreadsheets"),
)

TELEGRAM_CAPABILITIES = (
    CapabilityDefinition("telegram.publish_text", "Publish Messages", "Publish text messages to channels and groups.", "publish"),
    CapabilityDefinition("telegram.publish_photo", "Publish Photos", "Publish approved photos with captions.", "publish"),
    CapabilityDefinition("telegram.publish_video", "Publish Videos", "Publish video links or uploads with captions.", "publish"),
    CapabilityDefinition("telegram.publish_document", "Publish Documents", "Publish approved files.", "publish"),
    CapabilityDefinition("telegram.publish_album", "Publish Albums", "Publish media albums.", "publish"),
    CapabilityDefinition("telegram.schedule", "Schedule Posts", "Schedule Telegram posts.", "write"),
)

META_INSTAGRAM_CAPABILITIES = (
    CapabilityDefinition("instagram.publish_image", "Publish Images", "Publish image posts through Meta Graph API.", "publish", "instagram_content_publish"),
    CapabilityDefinition("instagram.publish_reel", "Publish Reels", "Publish short video Reels.", "publish", "instagram_content_publish"),
    CapabilityDefinition("instagram.publish_story", "Publish Stories", "Publish approved stories through Meta Graph API.", "publish", "instagram_content_publish"),
    CapabilityDefinition("instagram.publish_carousel", "Publish Carousels", "Publish carousel posts.", "publish", "instagram_content_publish"),
    CapabilityDefinition("instagram.read_comments", "Read Comments", "Read Instagram media comments.", "read", "instagram_manage_comments"),
    CapabilityDefinition("instagram.reply_comments", "Reply to Comments", "Reply to Instagram comments.", "send", "instagram_manage_comments"),
)

FACEBOOK_CAPABILITIES = (
    CapabilityDefinition("facebook.pages_publish", "Page Posts", "Publish and manage Facebook Page posts.", "publish", "pages_manage_posts"),
    CapabilityDefinition("facebook.photos", "Page Photos", "Publish Facebook Page photos.", "publish", "pages_manage_posts"),
    CapabilityDefinition("facebook.videos", "Page Videos", "Publish Facebook Page videos.", "publish", "pages_manage_posts"),
    CapabilityDefinition("facebook.read_comments", "Read Comments", "Read Page comments.", "read", "pages_read_engagement"),
    CapabilityDefinition("facebook.comments", "Comments", "Reply to Page comments.", "send", "pages_manage_engagement"),
    CapabilityDefinition("facebook.messenger", "Messenger", "Reply to Page Messenger threads.", "send", "pages_messaging"),
)

LINKEDIN_CAPABILITIES = (
    CapabilityDefinition("linkedin.publish_post", "Publish Posts", "Publish LinkedIn text posts.", "publish", "w_member_social"),
    CapabilityDefinition("linkedin.publish_image", "Publish Images", "Publish LinkedIn image posts.", "publish", "w_member_social"),
    CapabilityDefinition("linkedin.analytics", "Analytics", "Read post analytics when available.", "read", "r_member_social"),
)

YOUTUBE_CAPABILITIES = (
    CapabilityDefinition("youtube.upload", "Upload Videos", "Upload videos through YouTube Data API.", "publish", "https://www.googleapis.com/auth/youtube.upload"),
    CapabilityDefinition("youtube.edit", "Edit Metadata", "Update title, description, tags, status, and thumbnails.", "write", "https://www.googleapis.com/auth/youtube"),
    CapabilityDefinition("youtube.thumbnails", "Thumbnails", "Upload and update video thumbnails.", "write", "https://www.googleapis.com/auth/youtube"),
    CapabilityDefinition("youtube.analytics", "Channel Analytics", "Read channel and video analytics.", "read", "https://www.googleapis.com/auth/youtube.readonly"),
)

SHOPIFY_CAPABILITIES = (
    CapabilityDefinition("shopify.products", "Products", "Read and update Shopify products.", "write", "read_products write_products"),
    CapabilityDefinition("shopify.orders", "Orders", "Read order details and fulfillment signals.", "read", "read_orders"),
    CapabilityDefinition("shopify.customers", "Customers", "Read customer profiles and segments.", "read", "read_customers"),
    CapabilityDefinition("shopify.inventory", "Inventory", "Read and update inventory levels.", "write", "read_inventory write_inventory"),
    CapabilityDefinition("shopify.discounts", "Discounts", "Create and manage discount codes.", "write", "read_discounts write_discounts"),
    CapabilityDefinition("shopify.analytics", "Analytics", "Review storefront and commerce performance.", "read", "read_analytics"),
)

TIKTOK_CAPABILITIES = (
    CapabilityDefinition("tiktok.user", "User Profile", "Read TikTok account profile details.", "read", "user.info.basic"),
    CapabilityDefinition("tiktok.videos", "Videos", "Read and prepare short-form video workflows.", "read", "video.list"),
    CapabilityDefinition("tiktok.analytics", "Analytics", "Review video and account performance signals.", "read", "video.list"),
    CapabilityDefinition("tiktok.comments", "Comments", "Coordinate TikTok comment workflows.", "read", "user.info.basic"),
)

X_CAPABILITIES = (
    CapabilityDefinition("x.profile", "Profile", "Read X account profile details.", "read", "users.read"),
    CapabilityDefinition("x.posts", "Posts", "Read, draft, and publish X posts when approved.", "publish", "tweet.read tweet.write"),
    CapabilityDefinition("x.replies", "Replies", "Monitor and coordinate reply workflows.", "read", "tweet.read"),
    CapabilityDefinition("x.mentions", "Mentions", "Track brand mentions and activity.", "read", "tweet.read"),
)

DISCORD_CAPABILITIES = (
    CapabilityDefinition("discord.identity", "Identity", "Read Discord user identity.", "read", "identify"),
    CapabilityDefinition("discord.email", "Email", "Read Discord account email when granted.", "read", "email"),
    CapabilityDefinition("discord.guilds", "Servers", "List accessible Discord servers.", "read", "guilds"),
)

SLACK_CAPABILITIES = (
    CapabilityDefinition("slack.channels", "Channels", "Read Slack channel metadata.", "read", "channels:read"),
    CapabilityDefinition("slack.messages", "Messages", "Send approved Slack messages.", "send", "chat:write"),
    CapabilityDefinition("slack.users", "Users", "Read Slack user profile details.", "read", "users:read"),
    CapabilityDefinition("slack.threads", "Threads", "Coordinate Slack thread handoffs.", "write", "chat:write"),
)

NOTION_CAPABILITIES = (
    CapabilityDefinition("notion.workspace", "Workspace", "Connect a Notion workspace.", "read"),
    CapabilityDefinition("notion.pages", "Pages", "Read and update Notion pages.", "write"),
    CapabilityDefinition("notion.databases", "Databases", "Read and update Notion databases.", "write"),
    CapabilityDefinition("notion.tasks", "Tasks", "Coordinate task databases and briefs.", "write"),
)

GITHUB_CAPABILITIES = (
    CapabilityDefinition("github.profile", "Profile", "Read GitHub profile details.", "read", "read:user"),
    CapabilityDefinition("github.email", "Email", "Read GitHub account email.", "read", "user:email"),
    CapabilityDefinition("github.repos", "Repositories", "Inspect repositories and activity.", "read", "repo"),
    CapabilityDefinition("github.issues", "Issues", "Read and coordinate issue workflows.", "write", "repo"),
    CapabilityDefinition("github.pull_requests", "Pull Requests", "Review pull request metadata.", "read", "repo"),
)

DROPBOX_CAPABILITIES = (
    CapabilityDefinition("dropbox.account", "Account", "Read Dropbox account details.", "read", "account_info.read"),
    CapabilityDefinition("dropbox.files", "Files", "Read Dropbox file metadata and content.", "read", "files.metadata.read files.content.read"),
    CapabilityDefinition("dropbox.sharing", "Sharing", "Coordinate shared asset workflows.", "read", "sharing.read"),
)

ONEDRIVE_CAPABILITIES = (
    CapabilityDefinition("onedrive.profile", "Profile", "Read Microsoft profile details.", "read", "User.Read"),
    CapabilityDefinition("onedrive.files", "Files", "Read and update OneDrive files.", "write", "Files.ReadWrite.All"),
    CapabilityDefinition("onedrive.offline", "Offline Access", "Refresh OneDrive access when allowed.", "read", "offline_access"),
)

STRIPE_CAPABILITIES = (
    CapabilityDefinition("stripe.account", "Account", "Connect a Stripe account.", "read", "read_write"),
    CapabilityDefinition("stripe.payments", "Payments", "Review payments and balance signals.", "read", "read_write"),
    CapabilityDefinition("stripe.customers", "Customers", "Review customer and subscription data.", "read", "read_write"),
    CapabilityDefinition("stripe.invoices", "Invoices", "Coordinate invoice and revenue workflows.", "read", "read_write"),
)

OPENAI_CAPABILITIES = (
    CapabilityDefinition("openai.models", "Models", "Use OpenAI models in approved automation workflows.", "write"),
    CapabilityDefinition("openai.prompts", "Prompts", "Coordinate prompt and tool workflows.", "write"),
    CapabilityDefinition("openai.responses", "Responses", "Run model-powered response generation.", "write"),
)

CLAUDE_CAPABILITIES = (
    CapabilityDefinition("claude.models", "Models", "Use Claude models in approved automation workflows.", "write"),
    CapabilityDefinition("claude.writing", "Writing", "Coordinate writing and reasoning workflows.", "write"),
    CapabilityDefinition("claude.research", "Research", "Run research assistant workflows.", "write"),
)

ZAPIER_CAPABILITIES = (
    CapabilityDefinition("zapier.webhooks", "Webhooks", "Trigger Zapier webhook automations.", "send"),
    CapabilityDefinition("zapier.zaps", "Zaps", "Coordinate cross-app Zap workflows.", "write"),
    CapabilityDefinition("zapier.tasks", "Tasks", "Send approved tasks to Zapier.", "send"),
)

PROVIDERS: dict[str, ProviderDefinition] = {
    "google": ProviderDefinition(
        "google",
        "Google",
        "oauth2",
        "/images/providers/google.svg",
        "https://developers.google.com/identity/protocols/oauth2/scopes",
        GOOGLE_CAPABILITIES,
    ),
    "telegram": ProviderDefinition(
        "telegram",
        "Telegram",
        "bot_token",
        "/images/providers/telegram.svg",
        "https://core.telegram.org/bots/api",
        TELEGRAM_CAPABILITIES,
    ),
    "instagram": ProviderDefinition(
        "instagram",
        "Instagram",
        "meta_oauth2",
        "/images/providers/instagram.svg",
        "https://developers.facebook.com/documentation/instagram-platform/content-publishing",
        META_INSTAGRAM_CAPABILITIES,
    ),
    "facebook": ProviderDefinition(
        "facebook",
        "Facebook",
        "meta_oauth2",
        "/images/providers/facebook.svg",
        "https://developers.facebook.com/documentation/pages-api/posts",
        FACEBOOK_CAPABILITIES,
    ),
    "linkedin": ProviderDefinition(
        "linkedin",
        "LinkedIn",
        "oauth2",
        "/images/providers/linkedin.svg",
        "https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin",
        LINKEDIN_CAPABILITIES,
    ),
    "youtube": ProviderDefinition(
        "youtube",
        "YouTube",
        "oauth2",
        "/images/providers/youtube.svg",
        "https://developers.google.com/youtube/v3/docs/videos/insert",
        YOUTUBE_CAPABILITIES,
    ),
    "shopify": ProviderDefinition(
        "shopify",
        "Shopify",
        "oauth2",
        "/images/providers/shopify.svg",
        "https://shopify.dev/docs/api/admin-rest",
        SHOPIFY_CAPABILITIES,
    ),
    "tiktok": ProviderDefinition(
        "tiktok",
        "TikTok",
        "oauth2",
        "/images/providers/tiktok.svg",
        "https://developers.tiktok.com/doc/oauth-user-access-token-management",
        TIKTOK_CAPABILITIES,
    ),
    "x": ProviderDefinition(
        "x",
        "X",
        "oauth2",
        "/images/providers/x.svg",
        "https://developer.x.com/en/docs/authentication/oauth-2-0/authorization-code",
        X_CAPABILITIES,
    ),
    "discord": ProviderDefinition(
        "discord",
        "Discord",
        "oauth2",
        "/images/providers/discord.svg",
        "https://discord.com/developers/docs/topics/oauth2",
        DISCORD_CAPABILITIES,
    ),
    "slack": ProviderDefinition(
        "slack",
        "Slack",
        "oauth2",
        "/images/providers/slack.svg",
        "https://api.slack.com/authentication/oauth-v2",
        SLACK_CAPABILITIES,
    ),
    "notion": ProviderDefinition(
        "notion",
        "Notion",
        "oauth2",
        "/images/providers/notion.svg",
        "https://developers.notion.com/docs/authorization",
        NOTION_CAPABILITIES,
    ),
    "github": ProviderDefinition(
        "github",
        "GitHub",
        "oauth2",
        "/images/providers/github.svg",
        "https://docs.github.com/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps",
        GITHUB_CAPABILITIES,
    ),
    "dropbox": ProviderDefinition(
        "dropbox",
        "Dropbox",
        "oauth2",
        "/images/providers/dropbox.svg",
        "https://developers.dropbox.com/oauth-guide",
        DROPBOX_CAPABILITIES,
    ),
    "onedrive": ProviderDefinition(
        "onedrive",
        "OneDrive",
        "oauth2",
        "/images/providers/microsoftonedrive.svg",
        "https://learn.microsoft.com/en-us/graph/auth-v2-user",
        ONEDRIVE_CAPABILITIES,
    ),
    "stripe": ProviderDefinition(
        "stripe",
        "Stripe",
        "oauth2",
        "/images/providers/stripe.svg",
        "https://docs.stripe.com/connect/oauth-reference",
        STRIPE_CAPABILITIES,
    ),
    "openai": ProviderDefinition(
        "openai",
        "OpenAI",
        "api_key",
        "/images/providers/openai.svg",
        "https://platform.openai.com/docs",
        OPENAI_CAPABILITIES,
    ),
    "claude": ProviderDefinition(
        "claude",
        "Claude",
        "api_key",
        "/images/providers/claude.svg",
        "https://docs.anthropic.com",
        CLAUDE_CAPABILITIES,
    ),
    "zapier": ProviderDefinition(
        "zapier",
        "Zapier",
        "webhook",
        "/images/providers/zapier.svg",
        "https://platform.zapier.com/docs",
        ZAPIER_CAPABILITIES,
    ),
}
