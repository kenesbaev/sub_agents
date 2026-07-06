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


@lru_cache
def get_settings() -> Settings:
    return Settings()
