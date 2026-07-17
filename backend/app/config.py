from functools import lru_cache
from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Rebly AI API"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = "postgresql+psycopg://rebly:rebly@localhost:5432/rebly_ai"
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_pool_timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)
    database_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86400)
    database_connect_timeout_seconds: int = Field(default=10, ge=1, le=60)
    # ``None`` keeps old local-development behaviour without making production
    # depend on implicit schema mutations. Explicit environment values win.
    database_auto_create_schema: bool | None = None
    database_startup_backfill: bool | None = None
    scheduled_post_worker_enabled: bool = False
    scheduled_post_worker_poll_seconds: float = Field(default=5.0, ge=1.0, le=300.0)
    # Conservative at-most-once delivery: start with one outstanding provider
    # attempt per worker so a process crash cannot strand a whole claimed batch.
    scheduled_post_worker_batch_size: int = Field(default=1, ge=1, le=50)
    scheduled_post_worker_max_attempts: int = Field(default=3, ge=1, le=10)
    scheduled_post_worker_retry_base_seconds: float = Field(default=30.0, ge=1.0, le=3600.0)
    scheduled_post_worker_retry_max_seconds: float = Field(default=300.0, ge=1.0, le=21600.0)
    scheduled_post_worker_claim_stale_seconds: int = Field(default=300, ge=120, le=86400)
    jwt_secret: str = Field(default="change-me-in-local-env", min_length=16)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = Field(default=60 * 24 * 7, ge=5, le=60 * 24 * 30)
    local_password_auth_enabled: bool | None = None
    frontend_url: AnyHttpUrl = "http://127.0.0.1:3000"
    backend_url: AnyHttpUrl = "http://127.0.0.1:8000"
    cors_allowed_origins: str = ""
    trusted_hosts: str = ""
    cookie_secure: bool = False

    google_client_id: str = ""
    google_client_secret: str = ""
    google_auth_uri: str = "https://accounts.google.com/o/oauth2/auth"
    google_token_uri: str = "https://oauth2.googleapis.com/token"
    google_redirect_uri: str = "http://127.0.0.1:8000/api/auth/google/callback"
    google_connected_redirect_uri: str = "http://127.0.0.1:8000/api/connected-apps/google/callback"
    google_login_workspace_scopes: bool = False
    google_login_youtube_scopes: bool = False
    youtube_api_key: str = ""
    youtube_data_api_base_url: str = "https://www.googleapis.com/youtube/v3"
    youtube_analytics_api_base_url: str = "https://youtubeanalytics.googleapis.com/v2"
    youtube_http_timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    youtube_max_retries: int = Field(default=2, ge=0, le=4)
    youtube_retry_base_seconds: float = Field(default=0.25, ge=0.0, le=10.0)
    youtube_cache_ttl_seconds: int = Field(default=900, ge=30, le=86400)
    youtube_max_pages: int = Field(default=5, ge=1, le=10)
    youtube_snapshot_worker_enabled: bool = False
    youtube_snapshot_worker_run_in_api: bool = False
    youtube_snapshot_worker_poll_seconds: float = Field(default=60.0, ge=5.0, le=3600.0)
    youtube_snapshot_worker_batch_size: int = Field(default=10, ge=1, le=50)
    youtube_snapshot_worker_stale_seconds: int = Field(default=3600, ge=300, le=21600)
    youtube_upload_enabled: bool | None = None
    youtube_llm_api_url: str = ""
    youtube_llm_api_key: str = ""
    youtube_llm_model: str = ""
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
    linkedin_scopes: str = ""

    shopify_client_id: str = ""
    shopify_client_secret: str = ""
    shopify_shop_domain: str = ""
    shopify_api_version: str = "2026-07"
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

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def sqlalchemy_database_url(self) -> str:
        """Use psycopg 3 for managed-service PostgreSQL URL variants."""
        if self.database_url.startswith("postgres://"):
            return "postgresql+psycopg://" + self.database_url.removeprefix("postgres://")
        if self.database_url.startswith("postgresql://"):
            return "postgresql+psycopg://" + self.database_url.removeprefix("postgresql://")
        return self.database_url

    @property
    def auto_create_schema_enabled(self) -> bool:
        if self.database_auto_create_schema is not None:
            return self.database_auto_create_schema
        return self.app_env in {"development", "test"}

    @property
    def startup_backfill_enabled(self) -> bool:
        if self.database_startup_backfill is not None:
            return self.database_startup_backfill
        return self.app_env in {"development", "test"}

    @property
    def youtube_upload_runtime_enabled(self) -> bool:
        if self.youtube_upload_enabled is not None:
            return self.youtube_upload_enabled
        return not self.is_production

    @property
    def local_password_auth_runtime_enabled(self) -> bool:
        if self.local_password_auth_enabled is not None:
            return self.local_password_auth_enabled
        return not self.is_production

    def allowed_cors_origins(self) -> list[str]:
        origins = [str(self.frontend_url).rstrip("/")]
        origins.extend(part.strip().rstrip("/") for part in self.cors_allowed_origins.split(",") if part.strip())
        if not self.is_production:
            origins.extend(
                (
                    "http://localhost:3000",
                    "http://127.0.0.1:3000",
                    "http://localhost:4173",
                    "http://127.0.0.1:4173",
                )
            )
        return list(dict.fromkeys(origins))

    def allowed_hostnames(self) -> list[str]:
        hosts = [part.strip() for part in self.trusted_hosts.split(",") if part.strip()]
        backend_host = urlsplit(str(self.backend_url)).hostname
        if backend_host:
            hosts.append(backend_host)
        if not self.is_production:
            hosts.extend(("localhost", "127.0.0.1", "testserver"))
        return list(dict.fromkeys(hosts))

    @model_validator(mode="after")
    def validate_deployment_settings(self) -> "Settings":
        origins = self.allowed_cors_origins()
        if "*" in origins:
            raise ValueError("CORS wildcard origins are not allowed when credentials are enabled")
        for origin in origins:
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.path not in {"", "/"}:
                raise ValueError(f"Invalid CORS origin: {origin!r}")

        if not self.is_production:
            if self.scheduled_post_worker_retry_max_seconds < self.scheduled_post_worker_retry_base_seconds:
                raise ValueError(
                    "SCHEDULED_POST_WORKER_RETRY_MAX_SECONDS must be greater than or equal to "
                    "SCHEDULED_POST_WORKER_RETRY_BASE_SECONDS"
                )
            return self

        errors: list[str] = []
        def is_placeholder_secret(value: str) -> bool:
            normalized = value.strip().lower()
            placeholder_markers = (
                "change-me",
                "replace-me",
                "replace-with",
                "your-secret",
                "example-secret",
            )
            return any(marker in normalized for marker in placeholder_markers)

        if len(self.jwt_secret) < 32 or is_placeholder_secret(self.jwt_secret):
            errors.append("JWT_SECRET must be a unique random value of at least 32 characters")
        if self.jwt_algorithm not in {"HS256", "HS384", "HS512"}:
            errors.append("JWT_ALGORITHM must be HS256, HS384, or HS512")
        if self.access_token_minutes > 1440:
            errors.append("ACCESS_TOKEN_MINUTES must be 1440 or less in production")
        if self.local_password_auth_runtime_enabled:
            errors.append("LOCAL_PASSWORD_AUTH_ENABLED must be false in production until verification and abuse controls exist")
        if not self.google_client_id.strip() or not self.google_client_secret.strip():
            errors.append("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required because Google is the production login provider")
        if len(self.integration_encryption_secret) < 32 or is_placeholder_secret(self.integration_encryption_secret):
            errors.append("INTEGRATION_ENCRYPTION_SECRET must be a unique random value of at least 32 characters")
        if self.integration_encryption_secret == self.jwt_secret:
            errors.append("JWT_SECRET and INTEGRATION_ENCRYPTION_SECRET must be different")
        if not self.sqlalchemy_database_url.startswith("postgresql+psycopg://"):
            errors.append("production DATABASE_URL must use PostgreSQL")
        if not self.cookie_secure:
            errors.append("COOKIE_SECURE must be true in production")
        if self.auto_create_schema_enabled:
            errors.append("DATABASE_AUTO_CREATE_SCHEMA must be false in production; run Alembic before startup")
        if self.startup_backfill_enabled:
            errors.append("DATABASE_STARTUP_BACKFILL must be false in production; run data migrations separately")
        if self.youtube_snapshot_worker_run_in_api:
            errors.append("YOUTUBE_SNAPSHOT_WORKER_RUN_IN_API must be false in production; use the dedicated worker")
        if self.youtube_upload_runtime_enabled:
            errors.append(
                "YOUTUBE_UPLOAD_ENABLED must remain false until upload jobs have durable idempotency and DNS-pinned downloads"
            )
        if self.scheduled_post_worker_retry_max_seconds < self.scheduled_post_worker_retry_base_seconds:
            errors.append(
                "SCHEDULED_POST_WORKER_RETRY_MAX_SECONDS must be greater than or equal to "
                "SCHEDULED_POST_WORKER_RETRY_BASE_SECONDS"
            )
        if self.scheduled_post_worker_batch_size != 1:
            errors.append(
                "SCHEDULED_POST_WORKER_BATCH_SIZE must be 1 until provider delivery has durable idempotency"
            )

        for name, value in (("FRONTEND_URL", self.frontend_url), ("BACKEND_URL", self.backend_url)):
            parsed = urlsplit(str(value))
            host = parsed.hostname or ""
            try:
                loopback = ip_address(host).is_loopback
            except ValueError:
                loopback = host.lower() == "localhost"
            if parsed.scheme != "https" or loopback:
                errors.append(f"{name} must be a public HTTPS URL in production")

        backend_origin = urlsplit(str(self.backend_url))
        expected_callbacks = (
            ("GOOGLE_REDIRECT_URI", self.google_redirect_uri, "/api/auth/google/callback"),
            (
                "GOOGLE_CONNECTED_REDIRECT_URI",
                self.google_connected_redirect_uri,
                "/api/connected-apps/google/callback",
            ),
        )
        for name, value, expected_path in expected_callbacks:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or parsed.netloc != backend_origin.netloc
                or parsed.path != expected_path
                or parsed.query
                or parsed.fragment
                or parsed.username is not None
                or parsed.password is not None
            ):
                errors.append(f"{name} must be an exact HTTPS callback on BACKEND_URL")

        for origin in origins:
            if urlsplit(origin).scheme != "https":
                errors.append("all production CORS origins must use HTTPS")
                break
        allowed_hosts = self.allowed_hostnames()
        if not allowed_hosts:
            errors.append("at least one trusted host is required in production")
        if any("*" in host or host.startswith(".") for host in allowed_hosts):
            errors.append("production trusted hosts must be exact hostnames without wildcards")

        if errors:
            raise ValueError("Invalid production configuration: " + "; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
