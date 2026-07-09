from functools import lru_cache

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Rebly AI API"
    database_url: str = "postgresql+psycopg://rebly:rebly@localhost:5432/rebly_ai"
    jwt_secret: str = Field(default="change-me-in-local-env", min_length=16)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 24 * 7
    frontend_url: AnyHttpUrl = "http://127.0.0.1:3000"
    backend_url: AnyHttpUrl = "http://127.0.0.1:8000"
    cookie_secure: bool = False

    google_client_id: str = ""
    google_client_secret: str = ""
    google_auth_uri: str = "https://accounts.google.com/o/oauth2/auth"
    google_token_uri: str = "https://oauth2.googleapis.com/token"
    google_redirect_uri: str = "http://127.0.0.1:8000/api/auth/google/callback"
    google_connected_redirect_uri: str = "http://127.0.0.1:8000/api/connected-apps/google/callback"
    google_login_workspace_scopes: bool = False
    google_login_youtube_scopes: bool = False
    integration_encryption_secret: str = ""
    telegram_bot_token: str = ""
    telegram_target_chat_id: str = ""
    telegram_auto_publish: bool = False
    telegram_group_chat_id: str = ""
    telegram_atlas_bot_token: str = ""
    telegram_ava_bot_token: str = ""
    telegram_scout_bot_token: str = ""
    telegram_dex_bot_token: str = ""
    telegram_echo_bot_token: str = ""
    meta_graph_api_version: str = "v23.0"
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_oauth_uri: str = "https://www.facebook.com/v23.0/dialog/oauth"
    meta_token_uri: str = "https://graph.facebook.com/v23.0/oauth/access_token"
    meta_redirect_uri: str = "http://127.0.0.1:8000/api/connected-apps/meta/callback"
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_auth_uri: str = "https://www.linkedin.com/oauth/v2/authorization"
    linkedin_token_uri: str = "https://www.linkedin.com/oauth/v2/accessToken"
    linkedin_redirect_uri: str = "http://127.0.0.1:8000/api/connected-apps/linkedin/callback"

    shopify_client_id: str = ""
    shopify_client_secret: str = ""
    shopify_shop_domain: str = ""
    shopify_scopes: str = ""
    shopify_redirect_uri: str = ""
    shopify_auth_uri: str = ""
    shopify_token_uri: str = ""
    shopify_userinfo_uri: str = ""

    tiktok_client_id: str = ""
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_scopes: str = ""
    tiktok_redirect_uri: str = ""
    tiktok_auth_uri: str = ""
    tiktok_token_uri: str = ""
    tiktok_userinfo_uri: str = ""

    x_client_id: str = ""
    x_client_secret: str = ""
    x_scopes: str = ""
    x_redirect_uri: str = ""
    x_auth_uri: str = ""
    x_token_uri: str = ""
    x_userinfo_uri: str = ""

    discord_client_id: str = ""
    discord_client_secret: str = ""
    discord_scopes: str = ""
    discord_redirect_uri: str = ""
    discord_auth_uri: str = ""
    discord_token_uri: str = ""
    discord_userinfo_uri: str = ""

    slack_client_id: str = ""
    slack_client_secret: str = ""
    slack_scopes: str = ""
    slack_redirect_uri: str = ""
    slack_auth_uri: str = ""
    slack_token_uri: str = ""
    slack_userinfo_uri: str = ""

    notion_client_id: str = ""
    notion_client_secret: str = ""
    notion_scopes: str = ""
    notion_redirect_uri: str = ""
    notion_auth_uri: str = ""
    notion_token_uri: str = ""
    notion_userinfo_uri: str = ""

    github_client_id: str = ""
    github_client_secret: str = ""
    github_scopes: str = ""
    github_redirect_uri: str = ""
    github_auth_uri: str = ""
    github_token_uri: str = ""
    github_userinfo_uri: str = ""

    dropbox_client_id: str = ""
    dropbox_client_secret: str = ""
    dropbox_scopes: str = ""
    dropbox_redirect_uri: str = ""
    dropbox_auth_uri: str = ""
    dropbox_token_uri: str = ""
    dropbox_userinfo_uri: str = ""

    onedrive_client_id: str = ""
    onedrive_client_secret: str = ""
    onedrive_scopes: str = ""
    onedrive_redirect_uri: str = ""
    onedrive_auth_uri: str = ""
    onedrive_token_uri: str = ""
    onedrive_userinfo_uri: str = ""

    stripe_client_id: str = ""
    stripe_client_secret: str = ""
    stripe_scopes: str = ""
    stripe_redirect_uri: str = ""
    stripe_auth_uri: str = ""
    stripe_token_uri: str = ""
    stripe_userinfo_uri: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
