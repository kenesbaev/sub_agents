from __future__ import annotations

PROVIDER_KEY = "telegram"
CAPABILITIES = (
    "telegram.publish_text",
    "telegram.publish_photo",
    "telegram.publish_video",
    "telegram.publish_document",
    "telegram.publish_album",
    "telegram.schedule",
)
TOOLS = ("publish_social_post", "schedule_social_post")
