from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.connected_apps.service import write_activity
from app.integrations import (
    connected_account_credentials,
    default_connected_account_id,
    get_instagram_integration,
    get_telegram_integration,
    publish_to_platform,
    telegram_credentials,
)
from app.models import ScheduledPost, User
from app.schemas import PublishTargetResult
from app.token_crypto import decrypt_token


PROCESSING_STATUS = "processing"
RETRY_STATUS = "retry"
RECONCILIATION_STATUS = "reconciliation_required"
STALE_OUTCOME_ERROR = (
    "The previous provider attempt has no confirmed local outcome; manual reconciliation is required."
)
PROVIDER_OUTCOME_ERROR = (
    "The provider did not return a safely retryable outcome; manual reconciliation is required."
)
PREFLIGHT_RETRY_ERROR = "Pre-publish credential validation failed before external delivery; retry scheduled."
PREFLIGHT_FAILED_ERROR = "Pre-publish validation failed before external delivery."


class PermanentPreflightError(RuntimeError):
    """A definite local validation failure; no external request was sent."""


class RetryablePreflightError(RuntimeError):
    """A transient-looking local failure; no external request was sent."""


@dataclass(frozen=True)
class ClaimedPost:
    post_id: int
    claim_token: str


@dataclass(frozen=True)
class ScheduledPostBatchResult:
    claimed: int = 0
    published: int = 0
    retried: int = 0
    failed: int = 0
    reconciliation_required: int = 0
    skipped: int = 0
    stale_reconciled: int = 0


Publisher = Callable[..., PublishTargetResult]
Preflight = Callable[[Session, ScheduledPost], None]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def due_posts_statement(now: datetime, batch_size: int) -> Select[tuple[ScheduledPost]]:
    due_at = func.coalesce(ScheduledPost.next_attempt_at, ScheduledPost.publish_at)
    return (
        select(ScheduledPost)
        .where(
            ScheduledPost.status.in_(("scheduled", RETRY_STATUS)),
            due_at <= now,
        )
        .order_by(due_at.asc(), ScheduledPost.id.asc())
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )


def stale_claims_statement(cutoff: datetime, batch_size: int) -> Select[tuple[ScheduledPost]]:
    return (
        select(ScheduledPost)
        .where(
            ScheduledPost.status == PROCESSING_STATUS,
            or_(ScheduledPost.claimed_at.is_(None), ScheduledPost.claimed_at <= cutoff),
        )
        .order_by(ScheduledPost.claimed_at.asc(), ScheduledPost.id.asc())
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )


def claim_due_posts(
    session_factory: Callable[[], Session],
    settings: Settings,
    *,
    now: datetime | None = None,
    worker_id: str | None = None,
) -> list[ClaimedPost]:
    claimed_at = now or utc_now()
    owner = (worker_id or uuid4().hex)[:40]
    with session_factory() as db:
        posts = list(db.scalars(due_posts_statement(claimed_at, settings.scheduled_post_worker_batch_size)))
        claims: list[ClaimedPost] = []
        for post in posts:
            token = f"{owner}:{uuid4().hex}"[:96]
            post.status = PROCESSING_STATUS
            post.attempts = int(post.attempts or 0) + 1
            post.claimed_at = claimed_at
            post.claim_token = token
            post.error = None
            claims.append(ClaimedPost(post_id=post.id, claim_token=token))
        db.commit()
        return claims


def _write_worker_activity(
    db: Session,
    post: ScheduledPost,
    *,
    status: str,
    error: str | None,
    next_attempt_at: datetime | None = None,
    external_id: str | int | None = None,
) -> None:
    metadata: dict[str, object] = {
        "scheduledPostId": post.id,
        "attempt": int(post.attempts or 0),
    }
    if next_attempt_at is not None:
        metadata["nextAttemptAt"] = next_attempt_at.isoformat()
    write_activity(
        db,
        user_id=post.user_id,
        agent="scheduled-post-worker",
        service=post.platform,
        action="publish_scheduled_post",
        status=status,
        external_id=external_id,
        error=error,
        metadata_json=metadata,
    )


def reconcile_stale_claims(
    session_factory: Callable[[], Session],
    settings: Settings,
    *,
    now: datetime | None = None,
) -> int:
    checked_at = now or utc_now()
    cutoff = checked_at - timedelta(seconds=settings.scheduled_post_worker_claim_stale_seconds)
    with session_factory() as db:
        posts = list(db.scalars(stale_claims_statement(cutoff, settings.scheduled_post_worker_batch_size)))
        for post in posts:
            post.status = RECONCILIATION_STATUS
            post.error = STALE_OUTCOME_ERROR
            post.next_attempt_at = None
            post.claimed_at = None
            post.claim_token = None
            _write_worker_activity(db, post, status=RECONCILIATION_STATUS, error=STALE_OUTCOME_ERROR)
        db.commit()
        return len(posts)


def validate_preflight(db: Session, post: ScheduledPost) -> None:
    """Validate only local prerequisites, without contacting a provider."""
    try:
        if post.account_id is None:
            post.account_id = default_connected_account_id(
                db,
                user_id=post.user_id,
                platform=post.platform,
            )
        if post.platform == "telegram":
            if post.account_id is not None:
                connected_account_credentials(
                    db,
                    user_id=post.user_id,
                    platform="telegram",
                    account_id=post.account_id,
                )
            else:
                telegram_credentials(get_telegram_integration(db, post.user_id))
            return
        if post.platform == "instagram":
            if not (post.media_url or "").strip():
                raise PermanentPreflightError("Instagram scheduled publishing requires a public media URL.")
            if post.account_id is not None:
                connected_account_credentials(
                    db,
                    user_id=post.user_id,
                    platform="instagram",
                    account_id=post.account_id,
                )
            else:
                integration = get_instagram_integration(db, post.user_id)
                if not integration:
                    raise PermanentPreflightError("Instagram is not connected for this user.")
                decrypt_token(integration.encrypted_access_token)
            return
        raise PermanentPreflightError("This platform is not supported by scheduled publishing.")
    except PermanentPreflightError:
        raise
    except HTTPException as exc:
        raise PermanentPreflightError(PREFLIGHT_FAILED_ERROR) from exc
    except Exception as exc:
        raise RetryablePreflightError(PREFLIGHT_RETRY_ERROR) from exc


def retry_delay(settings: Settings, attempt: int) -> float:
    exponent = max(0, attempt - 1)
    return min(
        settings.scheduled_post_worker_retry_base_seconds * (2**exponent),
        settings.scheduled_post_worker_retry_max_seconds,
    )


def _conditional_status_update(
    db: Session,
    post: ScheduledPost,
    claim_token: str,
    *,
    status: str,
    error: str | None,
    next_attempt_at: datetime | None = None,
    external_id: str | int | None = None,
) -> bool:
    result = db.execute(
        update(ScheduledPost)
        .where(
            ScheduledPost.id == post.id,
            ScheduledPost.status == PROCESSING_STATUS,
            ScheduledPost.claim_token == claim_token,
        )
        .values(
            status=status,
            error=error,
            next_attempt_at=next_attempt_at,
            external_id=str(external_id) if external_id is not None else None,
            claimed_at=None,
            claim_token=None,
        )
    )
    if result.rowcount != 1:
        db.rollback()
        return False
    _write_worker_activity(
        db,
        post,
        status=status,
        error=error,
        next_attempt_at=next_attempt_at,
        external_id=external_id,
    )
    db.commit()
    return True


def process_claimed_post(
    session_factory: Callable[[], Session],
    settings: Settings,
    claim: ClaimedPost,
    *,
    now: datetime | None = None,
    publisher: Publisher = publish_to_platform,
    preflight: Preflight = validate_preflight,
) -> str:
    processed_at = now or utc_now()
    with session_factory() as db:
        post = db.scalar(
            select(ScheduledPost).where(
                ScheduledPost.id == claim.post_id,
                ScheduledPost.status == PROCESSING_STATUS,
                ScheduledPost.claim_token == claim.claim_token,
            )
        )
        if post is None:
            return "skipped"
        user = db.get(User, post.user_id)
        if user is None:
            updated = _conditional_status_update(
                db,
                post,
                claim.claim_token,
                status="failed",
                error="The scheduled-post owner no longer exists.",
            )
            return "failed" if updated else "skipped"

        try:
            preflight(db, post)
        except PermanentPreflightError as exc:
            updated = _conditional_status_update(
                db,
                post,
                claim.claim_token,
                status="failed",
                error=str(exc)[:500],
            )
            return "failed" if updated else "skipped"
        except RetryablePreflightError:
            if post.attempts < settings.scheduled_post_worker_max_attempts:
                next_attempt = processed_at + timedelta(seconds=retry_delay(settings, post.attempts))
                updated = _conditional_status_update(
                    db,
                    post,
                    claim.claim_token,
                    status=RETRY_STATUS,
                    error=PREFLIGHT_RETRY_ERROR,
                    next_attempt_at=next_attempt,
                )
                return "retried" if updated else "skipped"
            updated = _conditional_status_update(
                db,
                post,
                claim.claim_token,
                status="failed",
                error=PREFLIGHT_FAILED_ERROR,
            )
            return "failed" if updated else "skipped"

        try:
            result = publisher(
                db,
                user,
                platform=post.platform,
                text=post.content,
                media_url=post.media_url,
                media_data_url=None,
                media_type=post.media_type,
                media_name=None,
                run_id=post.run_id,
                source=post.source or "scheduler",
                account_id=post.account_id,
            )
        except Exception:
            updated = _conditional_status_update(
                db,
                post,
                claim.claim_token,
                status=RECONCILIATION_STATUS,
                error=PROVIDER_OUTCOME_ERROR,
            )
            return RECONCILIATION_STATUS if updated else "skipped"

        if result.ok:
            updated = _conditional_status_update(
                db,
                post,
                claim.claim_token,
                status="published",
                error=None,
                external_id=result.external_id,
            )
            return "published" if updated else "skipped"

        updated = _conditional_status_update(
            db,
            post,
            claim.claim_token,
            status=RECONCILIATION_STATUS,
            error=PROVIDER_OUTCOME_ERROR,
        )
        return RECONCILIATION_STATUS if updated else "skipped"


def process_scheduled_post_batch(
    session_factory: Callable[[], Session],
    settings: Settings,
    *,
    now: datetime | None = None,
    worker_id: str | None = None,
    publisher: Publisher = publish_to_platform,
    preflight: Preflight = validate_preflight,
) -> ScheduledPostBatchResult:
    processed_at = now or utc_now()
    stale_reconciled = reconcile_stale_claims(session_factory, settings, now=processed_at)
    claims = claim_due_posts(session_factory, settings, now=processed_at, worker_id=worker_id)
    counts = {
        "published": 0,
        "retried": 0,
        "failed": 0,
        RECONCILIATION_STATUS: 0,
        "skipped": 0,
    }
    for claim in claims:
        outcome = process_claimed_post(
            session_factory,
            settings,
            claim,
            now=processed_at,
            publisher=publisher,
            preflight=preflight,
        )
        counts[outcome] += 1
    return ScheduledPostBatchResult(
        claimed=len(claims),
        published=counts["published"],
        retried=counts["retried"],
        failed=counts["failed"],
        reconciliation_required=counts[RECONCILIATION_STATUS],
        skipped=counts["skipped"],
        stale_reconciled=stale_reconciled,
    )
