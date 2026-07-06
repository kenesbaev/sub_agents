from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connected_apps.providers import PROVIDERS, CapabilityDefinition, ProviderDefinition
from app.models import (
    ActivityLog,
    IntegrationAccount,
    IntegrationCapability,
    IntegrationProvider,
    IntegrationToken,
    ScheduledPost,
    User,
    UserIntegration,
)
from app.token_crypto import encrypt_token


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_provider_records(db: Session) -> dict[str, IntegrationProvider]:
    records: dict[str, IntegrationProvider] = {}
    for definition in PROVIDERS.values():
        provider = db.scalar(select(IntegrationProvider).where(IntegrationProvider.key == definition.key))
        if provider is None:
            provider = IntegrationProvider(
                key=definition.key,
                name=definition.name,
                auth_type=definition.auth_type,
                logo=definition.logo,
                docs_url=definition.docs_url,
            )
            db.add(provider)
            db.flush()
        else:
            provider.name = definition.name
            provider.auth_type = definition.auth_type
            provider.logo = definition.logo
            provider.docs_url = definition.docs_url
        sync_capabilities(db, provider, definition.capabilities)
        records[definition.key] = provider
    return records


def sync_capabilities(
    db: Session,
    provider: IntegrationProvider,
    capabilities: tuple[CapabilityDefinition, ...],
) -> None:
    for capability in capabilities:
        record = db.scalar(
            select(IntegrationCapability).where(
                IntegrationCapability.provider_id == provider.id,
                IntegrationCapability.key == capability.key,
            )
        )
        if record is None:
            record = IntegrationCapability(
                provider_id=provider.id,
                key=capability.key,
                name=capability.name,
                description=capability.description,
                scope=capability.scope,
                access_level=capability.access_level,
            )
            db.add(record)
        else:
            record.name = capability.name
            record.description = capability.description
            record.scope = capability.scope
            record.access_level = capability.access_level


def get_provider_record(db: Session, provider_key: str) -> IntegrationProvider:
    providers = ensure_provider_records(db)
    provider = providers.get(provider_key)
    if provider is None:
        raise KeyError(provider_key)
    return provider


def get_user_integration(
    db: Session,
    *,
    user_id: int,
    provider_id: int,
) -> UserIntegration | None:
    return db.scalar(
        select(UserIntegration).where(
            UserIntegration.user_id == user_id,
            UserIntegration.provider_id == provider_id,
        )
    )


def upsert_user_integration(
    db: Session,
    *,
    user_id: int,
    provider: IntegrationProvider,
    status: str = "connected",
) -> UserIntegration:
    integration = get_user_integration(db, user_id=user_id, provider_id=provider.id)
    now = utc_now()
    if integration is None:
        integration = UserIntegration(
            user_id=user_id,
            provider_id=provider.id,
            status=status,
            connected_at=now if status == "connected" else None,
        )
        db.add(integration)
        db.flush()
    else:
        integration.status = status
        integration.last_error = None
        if status == "connected":
            integration.connected_at = integration.connected_at or now
            integration.disconnected_at = None
        elif status == "disconnected":
            integration.disconnected_at = now
    return integration


def upsert_integration_account(
    db: Session,
    *,
    integration: UserIntegration,
    provider: IntegrationProvider,
    account_identifier: str,
    account_label: str | None,
    account_type: str | None,
    metadata_json: dict[str, Any] | None = None,
) -> IntegrationAccount:
    account = db.scalar(
        select(IntegrationAccount).where(
            IntegrationAccount.user_integration_id == integration.id,
            IntegrationAccount.account_identifier == account_identifier,
        )
    )
    has_default = db.scalar(
        select(IntegrationAccount).where(
            IntegrationAccount.user_integration_id == integration.id,
            IntegrationAccount.is_default.is_(True),
        )
    )
    if account is None:
        account = IntegrationAccount(
            user_integration_id=integration.id,
            provider_id=provider.id,
            account_identifier=account_identifier,
            account_label=account_label,
            account_type=account_type,
            is_default=has_default is None,
            metadata_json=metadata_json,
        )
        db.add(account)
        db.flush()
    else:
        account.account_label = account_label
        account.account_type = account_type
        account.metadata_json = metadata_json
    return account


def upsert_integration_token(
    db: Session,
    *,
    integration: UserIntegration,
    account: IntegrationAccount,
    access_token: str | None,
    refresh_token: str | None = None,
    token_type: str | None = None,
    expires_at: datetime | None = None,
    scopes: str | None = None,
) -> IntegrationToken:
    token = db.scalar(
        select(IntegrationToken).where(IntegrationToken.integration_account_id == account.id)
    )
    if token is None:
        token = IntegrationToken(
            user_integration_id=integration.id,
            integration_account_id=account.id,
        )
        db.add(token)
    if access_token:
        token.encrypted_access_token = encrypt_token(access_token)
    if refresh_token:
        token.encrypted_refresh_token = encrypt_token(refresh_token)
    token.token_type = token_type
    token.expires_at = expires_at
    token.scopes = scopes
    return token


def upsert_connected_account(
    db: Session,
    *,
    user_id: int,
    provider_key: str,
    account_identifier: str,
    account_label: str | None,
    account_type: str | None,
    access_token: str | None,
    refresh_token: str | None = None,
    token_type: str | None = None,
    expires_at: datetime | None = None,
    scopes: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> IntegrationAccount:
    provider = get_provider_record(db, provider_key)
    integration = upsert_user_integration(db, user_id=user_id, provider=provider, status="connected")
    account = upsert_integration_account(
        db,
        integration=integration,
        provider=provider,
        account_identifier=account_identifier,
        account_label=account_label,
        account_type=account_type,
        metadata_json=metadata_json,
    )
    upsert_integration_token(
        db,
        integration=integration,
        account=account,
        access_token=access_token,
        refresh_token=refresh_token,
        token_type=token_type,
        expires_at=expires_at,
        scopes=scopes,
    )
    write_activity(
        db,
        user_id=user_id,
        agent="system",
        service=provider_key,
        action="connect_account",
        status="connected",
        metadata_json={"accountId": account.id, "account": account_identifier},
    )
    return account


def disconnect_provider(db: Session, *, user_id: int, provider_key: str) -> None:
    provider = get_provider_record(db, provider_key)
    integration = get_user_integration(db, user_id=user_id, provider_id=provider.id)
    if integration is None:
        return
    integration.status = "disconnected"
    integration.disconnected_at = utc_now()
    integration.last_error = None
    tokens = db.scalars(select(IntegrationToken).where(IntegrationToken.user_integration_id == integration.id)).all()
    for token in tokens:
        db.delete(token)
    write_activity(
        db,
        user_id=user_id,
        agent="system",
        service=provider_key,
        action="disconnect",
        status="disconnected",
    )


def get_default_account(db: Session, *, user_id: int, provider_key: str) -> IntegrationAccount | None:
    provider = get_provider_record(db, provider_key)
    integration = get_user_integration(db, user_id=user_id, provider_id=provider.id)
    if integration is None or integration.status != "connected":
        return None
    account = db.scalar(
        select(IntegrationAccount).where(
            IntegrationAccount.user_integration_id == integration.id,
            IntegrationAccount.is_default.is_(True),
        )
    )
    if account is not None:
        return account
    return db.scalar(select(IntegrationAccount).where(IntegrationAccount.user_integration_id == integration.id))


def provider_status_payload(db: Session, user: User) -> dict[str, Any]:
    providers = ensure_provider_records(db)
    payloads: list[dict[str, Any]] = []
    connected_count = 0
    for key, definition in PROVIDERS.items():
        provider = providers[key]
        integration = get_user_integration(db, user_id=user.id, provider_id=provider.id)
        connected = bool(integration and integration.status == "connected")
        if connected:
            connected_count += 1
        accounts = []
        if integration:
            account_records = db.scalars(
                select(IntegrationAccount)
                .where(IntegrationAccount.user_integration_id == integration.id)
                .order_by(IntegrationAccount.is_default.desc(), IntegrationAccount.created_at.asc())
            ).all()
            accounts = [
                {
                    "id": account.id,
                    "identifier": account.account_identifier,
                    "label": account.account_label,
                    "type": account.account_type,
                    "isDefault": account.is_default,
                    "metadata": account.metadata_json or {},
                    "connectedAt": account.created_at,
                }
                for account in account_records
            ]
        payloads.append(
            {
                "key": key,
                "name": definition.name,
                "authType": definition.auth_type,
                "logo": definition.logo,
                "docsUrl": definition.docs_url,
                "status": "Connected" if connected else "Not Connected",
                "connected": connected,
                "connectedAt": integration.connected_at if integration else None,
                "disconnectedAt": integration.disconnected_at if integration else None,
                "lastError": integration.last_error if integration else None,
                "accounts": accounts,
                "capabilities": [
                    {
                        "key": capability.key,
                        "name": capability.name,
                        "description": capability.description,
                        "scope": capability.scope,
                        "accessLevel": capability.access_level,
                    }
                    for capability in definition.capabilities
                ],
            }
        )
    return {
        "connectedCount": connected_count,
        "totalCount": len(payloads),
        "providers": payloads,
    }


def write_activity(
    db: Session,
    *,
    user_id: int,
    service: str,
    action: str,
    status: str,
    agent: str | None = None,
    external_id: str | int | None = None,
    error: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> ActivityLog:
    log = ActivityLog(
        user_id=user_id,
        agent=agent,
        service=service,
        action=action,
        status=status,
        external_id=str(external_id) if external_id is not None else None,
        error=error,
        metadata_json=metadata_json,
    )
    db.add(log)
    return log


def list_activity(db: Session, *, user_id: int, limit: int = 50) -> list[ActivityLog]:
    return db.scalars(
        select(ActivityLog)
        .where(ActivityLog.user_id == user_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
    ).all()


def create_scheduled_post(
    db: Session,
    *,
    user_id: int,
    platform: str,
    content: str,
    publish_at: datetime,
    account_id: int | None = None,
    media_url: str | None = None,
    media_type: str | None = None,
    timezone: str = "UTC",
    repeat_rule: str | None = None,
    source: str | None = None,
    run_id: str | None = None,
) -> ScheduledPost:
    post = ScheduledPost(
        user_id=user_id,
        platform=platform,
        account_id=account_id,
        content=content,
        media_url=media_url,
        media_type=media_type,
        publish_at=publish_at,
        timezone=timezone,
        repeat_rule=repeat_rule,
        status="scheduled",
        source=source,
        run_id=run_id,
    )
    db.add(post)
    write_activity(
        db,
        user_id=user_id,
        agent="scheduler",
        service=platform,
        action="schedule_post",
        status="scheduled",
        metadata_json={"publishAt": publish_at.isoformat(), "timezone": timezone},
    )
    return post


def list_scheduled_posts(db: Session, *, user_id: int, limit: int = 100) -> list[ScheduledPost]:
    return db.scalars(
        select(ScheduledPost)
        .where(ScheduledPost.user_id == user_id)
        .order_by(ScheduledPost.publish_at.desc())
        .limit(limit)
    ).all()
