from __future__ import annotations

PROVIDERS = ("instagram", "facebook")
CAPABILITIES = (
    "instagram.publish_image",
    "instagram.publish_carousel",
    "instagram.publish_reel",
    "instagram.comments",
    "instagram.direct",
    "facebook.pages_publish",
    "facebook.comments",
    "facebook.messenger",
)
TOOLS = ("publish_social_post", "schedule_social_post", "get_social_comments", "reply_to_comment")
