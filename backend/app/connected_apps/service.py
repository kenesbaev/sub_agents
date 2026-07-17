from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.connected_apps.providers import PROVIDERS, CapabilityDefinition
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


PROVIDER_RUNTIME_ACTIONS: dict[str, list[str]] = {
    "google": ["gmail", "calendar", "sheets"],
    "telegram": ["approved_publish", "scheduled_publish"],
    "instagram": ["approved_publish", "scheduled_publish"],
    "youtube": ["growth_analysis", "owned_channel_analytics"],
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def insert_unique_do_nothing(
    db: Session,
    model: type,
    *,
    values: dict[str, Any],
    index_elements: list[str],
) -> None:
    """Insert a unique row without turning a concurrent winner into HTTP 500."""
    dialect_name = db.get_bind().dialect.name
    table = model.__table__
    if dialect_name == "postgresql":
        statement = postgresql_insert(table).values(**values).on_conflict_do_nothing(index_elements=index_elements)
        db.execute(statement)
        return
    if dialect_name == "sqlite":
        statement = sqlite_insert(table).values(**values).on_conflict_do_nothing(index_elements=index_elements)
        db.execute(statement)
        return

    try:
        with db.begin_nested():
            db.add(model(**values))
            db.flush()
    except IntegrityError:
        # The unique winner is loaded by the caller in the outer transaction.
        pass


def normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


STALE_CONNECTING_AFTER = timedelta(minutes=15)
SENSITIVE_METADATA_KEYS = {
    "access_token",
    "refresh_token",
    "id_token",
    "token",
    "secret",
    "client_secret",
    "api_key",
    "password",
    "authorization",
    "cookie",
    "credential",
    "credentials",
    "code_verifier",
    "webhook",
    "webhook_url",
}


def metadata_key_is_sensitive(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return (
        normalized in SENSITIVE_METADATA_KEYS
        or normalized.endswith(("_token", "_secret", "_password", "_api_key", "_credential", "_credentials"))
    )


def sanitize_metadata(value: Any, *, _depth: int = 0) -> Any:
    if _depth >= 6:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {
            str(key)[:160]: sanitize_metadata(item, _depth=_depth + 1)
            for key, item in list(value.items())[:100]
            if not metadata_key_is_sensitive(key)
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_metadata(item, _depth=_depth + 1) for item in list(value)[:100]]
    if isinstance(value, str):
        return value[:4000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:1000]


def integration_connection_state(integration: UserIntegration | None, tokens: list[IntegrationToken]) -> tuple[str, str, bool]:
    if integration is None or integration.status in {"not_connected", "disconnected"}:
        return "not_connected", "Not Connected", False
    now = utc_now()
    if integration.status == "connecting":
        updated_at = normalize_datetime(integration.updated_at)
        if updated_at is not None and updated_at <= now - STALE_CONNECTING_AFTER:
            integration.status = "error"
            integration.last_error = integration.last_error or "Authorization was not completed. Try connecting again."
            return "error", "Error", False
        return "connecting", "Connecting", False
    if integration.status == "connected":
        expired_tokens = [
            token
            for token in tokens
            if (expires_at := normalize_datetime(token.expires_at)) is not None and expires_at <= now
        ]
        if expired_tokens:
            integration.status = "reconnect_required" if any(token.encrypted_refresh_token for token in expired_tokens) else "expired"
            integration.last_error = integration.last_error or "Authorization expired. Reconnect this app."
        else:
            return "connected", "Connected", True
    if integration.status == "reconnect_required":
        return "reconnect_required", "Reconnect Required", False
    if integration.status == "expired":
        return "expired", "Expired", False
    if integration.status == "error":
        return "error", "Error", False
    return integration.status, integration.status.replace("_", " ").title(), False


def ensure_provider_records(db: Session) -> dict[str, IntegrationProvider]:
    existing_providers = db.scalars(select(IntegrationProvider)).all()
    records = {provider.key: provider for provider in existing_providers}
    for definition in PROVIDERS.values():
        provider = records.get(definition.key)
        if provider is None:
            provider = IntegrationProvider(
                key=definition.key,
                name=definition.name,
                auth_type=definition.auth_type,
                logo=definition.logo,
                docs_url=definition.docs_url,
            )
            db.add(provider)
            records[definition.key] = provider
        else:
            provider.name = definition.name
            provider.auth_type = definition.auth_type
            provider.logo = definition.logo
            provider.docs_url = definition.docs_url
    db.flush()

    provider_ids = [provider.id for provider in records.values()]
    capability_records = (
        db.scalars(select(IntegrationCapability).where(IntegrationCapability.provider_id.in_(provider_ids))).all()
        if provider_ids
        else []
    )
    capabilities_by_key = {
        (record.provider_id, record.key): record
        for record in capability_records
    }
    for definition in PROVIDERS.values():
        provider = records[definition.key]
        sync_capabilities(
            db,
            provider,
            definition.capabilities,
            existing=capabilities_by_key,
        )
    return records


def sync_capabilities(
    db: Session,
    provider: IntegrationProvider,
    capabilities: tuple[CapabilityDefinition, ...],
    *,
    existing: dict[tuple[int, str], IntegrationCapability] | None = None,
) -> None:
    for capability in capabilities:
        record = (existing or {}).get((provider.id, capability.key))
        if existing is None:
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
            if existing is not None:
                existing[(provider.id, capability.key)] = record
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
        insert_unique_do_nothing(
            db,
            UserIntegration,
            values={
                "user_id": user_id,
                "provider_id": provider.id,
                "status": status,
                "connected_at": now if status == "connected" else None,
            },
            index_elements=["user_id", "provider_id"],
        )
        db.flush()
        integration = get_user_integration(db, user_id=user_id, provider_id=provider.id)
        if integration is None:
            raise RuntimeError("Unable to load the user integration after conflict-safe insert")
    integration.status = status
    integration.last_error = None
    if status == "connected":
        integration.connected_at = integration.connected_at or now
        integration.disconnected_at = None
    elif status == "disconnected":
        integration.disconnected_at = now
    return integration


def set_user_integration_status(
    db: Session,
    *,
    user_id: int,
    provider_key: str,
    status: str,
    last_error: str | None = None,
) -> UserIntegration:
    provider = get_provider_record(db, provider_key)
    integration = upsert_user_integration(db, user_id=user_id, provider=provider, status=status)
    integration.last_error = last_error
    if status in {"connecting", "connected"}:
        integration.disconnected_at = None
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
    safe_metadata = sanitize_metadata(metadata_json or {})
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
        insert_unique_do_nothing(
            db,
            IntegrationAccount,
            values={
                "user_integration_id": integration.id,
                "provider_id": provider.id,
                "account_identifier": account_identifier,
                "account_label": account_label,
                "account_type": account_type,
                "is_default": has_default is None,
                "metadata_json": safe_metadata,
            },
            index_elements=["user_integration_id", "account_identifier"],
        )
        db.flush()
        account = db.scalar(
            select(IntegrationAccount).where(
                IntegrationAccount.user_integration_id == integration.id,
                IntegrationAccount.account_identifier == account_identifier,
            )
        )
        if account is None:
            raise RuntimeError("Unable to load the integration account after conflict-safe insert")
    account.account_label = account_label
    account.account_type = account_type
    account.metadata_json = safe_metadata
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
        select(IntegrationToken).where(
            IntegrationToken.user_integration_id == integration.id,
            IntegrationToken.integration_account_id == account.id,
        )
    )
    if token is None:
        insert_unique_do_nothing(
            db,
            IntegrationToken,
            values={
                "user_integration_id": integration.id,
                "integration_account_id": account.id,
            },
            index_elements=["user_integration_id", "integration_account_id"],
        )
        db.flush()
        token = db.scalar(
            select(IntegrationToken).where(
                IntegrationToken.user_integration_id == integration.id,
                IntegrationToken.integration_account_id == account.id,
            )
        )
        if token is None:
            raise RuntimeError("Unable to load the integration token after conflict-safe insert")
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


def granted_scope_values(value: str | None) -> set[str]:
    return {scope for scope in (value or "").replace(",", " ").split() if scope}


def capability_is_granted(capability: CapabilityDefinition, granted_scopes: set[str], *, connected: bool) -> bool:
    required = granted_scope_values(capability.scope)
    return connected and (not required or required.issubset(granted_scopes))


def provider_status_payload(db: Session, user: User) -> dict[str, Any]:
    providers = ensure_provider_records(db)
    provider_ids = [provider.id for provider in providers.values()]
    integration_records = db.scalars(
        select(UserIntegration).where(
            UserIntegration.user_id == user.id,
            UserIntegration.provider_id.in_(provider_ids),
        )
    ).all()
    integrations_by_provider: dict[int, UserIntegration] = {}
    for integration_record in integration_records:
        integrations_by_provider.setdefault(integration_record.provider_id, integration_record)

    integration_ids = [integration.id for integration in integrations_by_provider.values()]
    token_records = (
        db.scalars(select(IntegrationToken).where(IntegrationToken.user_integration_id.in_(integration_ids))).all()
        if integration_ids
        else []
    )
    tokens_by_integration: dict[int, list[IntegrationToken]] = {}
    for token in token_records:
        tokens_by_integration.setdefault(token.user_integration_id, []).append(token)

    account_records_all = (
        db.scalars(
            select(IntegrationAccount)
            .where(IntegrationAccount.user_integration_id.in_(integration_ids))
            .order_by(
                IntegrationAccount.user_integration_id,
                IntegrationAccount.is_default.desc(),
                IntegrationAccount.created_at.asc(),
            )
        ).all()
        if integration_ids
        else []
    )
    accounts_by_integration: dict[int, list[IntegrationAccount]] = {}
    for account in account_records_all:
        accounts_by_integration.setdefault(account.user_integration_id, []).append(account)

    payloads: list[dict[str, Any]] = []
    connected_count = 0
    for key, definition in PROVIDERS.items():
        provider = providers[key]
        integration = integrations_by_provider.get(provider.id)
        tokens = tokens_by_integration.get(integration.id, []) if integration else []
        connection_state, status_text, connected = integration_connection_state(integration, tokens)
        if connected:
            connected_count += 1
        account_records = accounts_by_integration.get(integration.id, []) if integration else []
        scopes_by_account = {
            token.integration_account_id: granted_scope_values(token.scopes)
            for token in tokens
        }
        default_account = account_records[0] if account_records else None
        granted_scopes = scopes_by_account.get(default_account.id, set()) if default_account else set()
        accounts = [
            {
                "id": account.id,
                "identifier": account.account_identifier,
                "label": account.account_label,
                "type": account.account_type,
                "isDefault": account.is_default,
                "metadata": sanitize_metadata(account.metadata_json or {}),
                "connectedAt": account.created_at,
                "grantedCapabilities": [
                    capability.key
                    for capability in definition.capabilities
                    if capability_is_granted(
                        capability,
                        scopes_by_account.get(account.id, set()),
                        connected=bool(connected),
                    )
                ],
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
                "status": status_text,
                "connectionState": connection_state,
                "connected": connected,
                "connectedAt": integration.connected_at if integration else None,
                "disconnectedAt": integration.disconnected_at if integration else None,
                "lastError": integration.last_error if integration else None,
                "runtimeState": "available" if key in PROVIDER_RUNTIME_ACTIONS else "connection_only",
                "runtimeActions": PROVIDER_RUNTIME_ACTIONS.get(key, []),
                "accounts": accounts,
                "capabilities": [
                    {
                        "key": capability.key,
                        "name": capability.name,
                        "description": capability.description,
                        "scope": "",
                        "accessLevel": capability.access_level,
                        "granted": capability_is_granted(capability, granted_scopes, connected=bool(connected)),
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
        metadata_json=sanitize_metadata(metadata_json or {}),
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
