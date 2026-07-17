# Scheduled-post worker

Run scheduled delivery in its own process, never in an API replica:

```powershell
python -m app.scheduled_posts.worker_main
```

Required deployment settings:

```dotenv
APP_ENV=production
SCHEDULED_POST_WORKER_ENABLED=true
SCHEDULED_POST_WORKER_POLL_SECONDS=5
SCHEDULED_POST_WORKER_BATCH_SIZE=10
SCHEDULED_POST_WORKER_MAX_ATTEMPTS=3
SCHEDULED_POST_WORKER_RETRY_BASE_SECONDS=30
SCHEDULED_POST_WORKER_RETRY_MAX_SECONDS=300
SCHEDULED_POST_WORKER_CLAIM_STALE_SECONDS=300
```

The worker refuses to start unless PostgreSQL is reachable and Alembic is at
head. Multiple replicas may run: due rows are claimed in a short transaction
using `FOR UPDATE SKIP LOCKED`, moved to `processing`, and protected by a unique
claim token. Batch size and polling are bounded.

## Delivery guarantees

Telegram and Instagram do not provide a reliable idempotency key for this
flow, so this worker deliberately implements **at-most-once automatic external
delivery**, not blind at-least-once retries.

- A local preflight failure before any provider call may retry with exponential
  backoff, up to `MAX_ATTEMPTS`.
- A definite local validation error becomes `failed` without contacting the
  provider.
- A provider error, network timeout, unexpected exception during delivery, or
  stale `processing` claim becomes `reconciliation_required` and is never sent
  again automatically. An operator must check the provider before deciding
  whether to create a new scheduled post.
- Provider success becomes `published` with its external identifier in the
  same local transaction as activity/social-post records.

This conservative rule prevents duplicate public posts after the provider
accepted a request but the worker crashed before committing local state.
Worker errors and activity metadata contain only post IDs, attempts, status,
and retry timestamps; content, credentials, tokens, and raw exception strings
are not logged by the worker.

`repeat_rule` is retained as request metadata, but recurring schedule expansion
is not currently implemented. Each `ScheduledPost` row represents exactly one
external delivery attempt sequence.
