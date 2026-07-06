from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleConfigResponse(BaseModel):
    client_id: str


class GoogleCredentialRequest(BaseModel):
    credential: str = Field(min_length=20, max_length=4096)


class UserResponse(BaseModel):
    id: int
    email: EmailStr
    first_name: str | None
    last_name: str | None
    avatar_url: str | None
    google_connected: bool
    created_at: datetime


class AuthResponse(BaseModel):
    user: UserResponse


class TelegramBotStatus(BaseModel):
    connected: bool
    target_chat_id: str | None = None
    bot_username: str | None = None
    updated_at: datetime | None = None


class InstagramStatus(BaseModel):
    connected: bool
    ig_user_id: str | None = None
    username: str | None = None
    updated_at: datetime | None = None


class IntegrationsResponse(BaseModel):
    telegram_bot: TelegramBotStatus
    instagram: InstagramStatus


class TelegramBotConnectRequest(BaseModel):
    bot_token: str = Field(min_length=9, max_length=256)
    target_chat_id: str = Field(min_length=1, max_length=255)


class InstagramConnectRequest(BaseModel):
    access_token: str = Field(min_length=20, max_length=4096)
    ig_user_id: str = Field(min_length=2, max_length=255)


class PublishTelegramRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    run_id: str | None = Field(default=None, max_length=80)
    source: str | None = Field(default=None, max_length=80)


class PublishTelegramResponse(BaseModel):
    ok: bool
    platform: str = "telegram"
    message_id: int | None = None
    chat_id: str | int | None = None


PublishPlatform = Literal["telegram", "instagram", "facebook", "linkedin", "youtube"]


class PublishSocialRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    platforms: list[PublishPlatform] = Field(default_factory=lambda: ["telegram"], min_length=1, max_length=5)
    media_url: str | None = Field(default=None, max_length=2048)
    media_data_url: str | None = None
    media_type: str | None = Field(default=None, max_length=120)
    media_name: str | None = Field(default=None, max_length=255)
    publish_at: datetime | None = None
    timezone: str = Field(default="UTC", max_length=80)
    repeat_rule: str | None = Field(default=None, max_length=160)
    run_id: str | None = Field(default=None, max_length=80)
    source: str | None = Field(default=None, max_length=80)


class PublishTargetResult(BaseModel):
    platform: PublishPlatform
    ok: bool
    external_id: str | int | None = None
    error: str | None = None


class PublishSocialResponse(BaseModel):
    ok: bool
    results: list[PublishTargetResult]
