# Teamora AI production runbook

This runbook deploys the current application as a single-host production stack.
It is intentionally fail-closed: PostgreSQL, backend, frontend, and the
agent port are not published publicly. Only Nginx binds to the host loopback
interface, where a TLS load balancer or host reverse proxy must reach it.

## Topology and boundaries

- The public HTTPS origin terminates TLS at a managed load balancer, CDN, or
  host reverse proxy and forwards to `127.0.0.1:8080`.
- Nginx routes `/api/agents/*` privately to `agent:4173`, `/api/*` to
  `backend:8000`, and everything else to `frontend:3000`.
- The browser never receives an internal service URL. The Agent API verifies
  the signed `rebly_session` JWT and ignores client-supplied account identity.
- PostgreSQL exists only on Docker's internal `data` network. Redis is not
  deployed until a runtime component actually uses it.
- `youtube-worker` is the only snapshot worker. API containers keep
  `YOUTUBE_SNAPSHOT_WORKER_RUN_IN_API=false`.
- `scheduled-post-worker` is the only scheduled publisher and starts with
  `SCHEDULED_POST_WORKER_BATCH_SIZE=1`. Do not increase it until dispatch-state
  metrics and crash reconciliation are proven.
- Agent memory remains on one named volume, so do **not** scale the agent
  service beyond one replica until run state and memory are moved to a shared
  store.

## Host prerequisites

1. A Linux host with Docker Engine and Docker Compose v2, at least 4 CPU, 16 GB
   RAM, 80 GB SSD, synchronized UTC time, and restricted SSH access.
2. DNS for the production hostname and a TLS 1.2+ certificate at the upstream
   load balancer/reverse proxy. Redirect HTTP to HTTPS there.
3. Firewall rules exposing only 443 (and restricted SSH). Do not expose 3000,
   4173, 5432, or the configured `HTTP_PORT` to the internet.
4. Encrypted off-site backup storage and an alert destination.

## First deployment

1. Copy `deploy/production.env.example` to `.env.production` and run
   `chmod 600 .env.production`.
2. Replace the hostname everywhere. Generate three different secrets with
   `openssl rand -hex 32`; use a separate random, URL-safe PostgreSQL password.
   Never reuse `JWT_SECRET` as the integration encryption key.
3. Configure Google OAuth login credentials. Local password login is disabled
   in production, so a release without working Google login is blocked.
4. Add only the provider credentials that are enabled. Register each HTTPS
   callback exactly as written in `.env.production` at the provider.
5. Put account-level request and spend limits on the model provider key.
6. Validate without printing secrets:

   ```sh
   python3 deploy/check_env.py .env.production
   docker compose --env-file .env.production -f compose.production.yml config --quiet
   ```

7. Deploy:

   ```sh
   SKIP_BACKUP=1 bash deploy/scripts/deploy.sh .env.production
   ```

   Omit `SKIP_BACKUP=1` on every later deployment. The migration container must
   finish successfully before the API becomes healthy.

8. Configure the upstream TLS proxy to send `Host` and
   `X-Forwarded-Proto: https` to `127.0.0.1:${HTTP_PORT}`. It must **overwrite**
   `X-Forwarded-For` with exactly one canonical client IP; never append or pass
   a client-supplied value. Nginx is deliberately loopback-only and uses that
   single address for per-client connection and rate limits.

## Release gates and smoke tests

Before allowing general traffic, verify all of the following:

- `docker compose --env-file .env.production -f compose.production.yml ps`
  reports every long-running service healthy and `migrate` exited with code 0.
- `https://YOUR_HOST/nginx-health` and `/api/health` return 200.
- An unauthenticated `/api/agents/capabilities` request returns 401.
- Login sets a `Secure`, `HttpOnly`, `SameSite=Lax` session cookie; the same
  authenticated browser can open Dashboard and Office and call Agent API.
- A second test user cannot access or cancel the first user's run.
- Run one inexpensive direct AI canary and one team canary. Confirm latency,
  provider request count, and account spend before increasing concurrency.
- Connect and disconnect each enabled OAuth provider using a test account.
  Google reads may be canaried; Google write tools are intentionally disabled
  until durable idempotency and unknown-outcome reconciliation are implemented.
  Publishing requires separate test content and explicit approval; never test
  against a real audience first. `YOUTUBE_UPLOAD_ENABLED` remains false until
  upload dispatch has durable idempotency and DNS-pinned downloads.

## Routine deployment

Use an immutable `IMAGE_TAG` for every release, retain the previous tag, and run:

```sh
bash deploy/scripts/deploy.sh .env.production
```

The script validates configuration, backs up PostgreSQL and agent memory,
builds images, applies Alembic migrations, starts the stack, and checks private
readiness endpoints. Do not deploy when the working tree is dirty; build from a
reviewed commit and record the commit SHA with the image tag.

## Backup policy

Run `bash deploy/scripts/backup.sh .env.production` at least daily and before
every migration. The script creates a PostgreSQL custom-format dump plus a
briefly quiesced `agent-data` archive, SHA-256 checksums, and user-only file
permissions. Set `BACKUP_UPLOAD_COMMAND` to a trusted executable that accepts
the four artifact paths and uploads them to encrypted off-site storage. Backups
fail the release gate when that hook is absent; only a deliberate drill may use
`REQUIRE_OFFSITE_UPLOAD=0`.

After a confirmed off-site upload, the script keeps the newest seven local
backup sets by default and removes older matching DB/agent pairs. It also aborts
before backup when less than 10 GiB is free. Tune both reviewed bounds in the
environment file and alert on host free space independently.

- Encrypt and copy backups off-host; a local named volume is not a backup.
- Keep daily, weekly, and monthly retention appropriate to the product's data
  policy. Provider tokens make database dumps highly sensitive.
- Snapshot Docker volumes only as a secondary measure. The PostgreSQL dump is
  the portable recovery artifact.
- Test a restoration in an isolated environment at least monthly and record
  achieved RPO/RTO.

## Restore

Restoration is destructive and intentionally requires confirmation:

```sh
CONFIRM_RESTORE=YES bash deploy/scripts/restore.sh backups/FILE.dump .env.production
```

The script verifies the PostgreSQL and matching agent-data checksums, creates a
new safety backup, stops application traffic, restores both state stores,
applies forward migrations, restarts the stack, and checks backend readiness. Afterward repeat
every authenticated smoke test. Do not restore a production dump into a less
trusted environment without rotating provider tokens and user credentials.

## Application rollback

Database migrations are forward-only by default. Roll back application images
only when the earlier release is documented as compatible with the current
schema:

```sh
CONFIRM_ROLLBACK=YES ROLLBACK_IMAGE_TAG=PREVIOUS_TAG \
  bash deploy/scripts/rollback.sh .env.production
```

Set `ROLLBACK_PULL=1` if images are stored in a registry. The script backs up
the database and replaces app containers without running the older migration
image. If the schema is incompatible, stop traffic and either deploy a forward
fix or restore the pre-deployment backup; do not run an improvised Alembic
downgrade on production.

## Operations and limits

- Start with one agent replica, two or fewer simultaneous team runs, and the
  configured provider concurrency of eight, capped at four calls per account.
  A team request is charged eight rate-limit units; web search is capped at ten
  total results per provider request, and unfinished clarification state expires
  after 15 minutes. Increase only from observed p95, error rate, memory,
  provider RPM/TPM, and spend.
- Keep the standalone Telegram bridge disabled. It is not part of the Compose
  release and must not be added until Telegram identities are linked to real
  application users with an allowlist.
- Alert on container restarts, readiness failures, PostgreSQL connections/disk,
  scheduled-post retries/manual-reconciliation state, HTTP 5xx, AI
  429/5xx/timeouts, queue rejection, OAuth refresh failures, publishing errors,
  and daily model cost.
- Compose enforces initial CPU, memory, process, read-only filesystem, and
  private-network bounds. Nginx uses Docker DNS re-resolution so service
  recreation does not leave stale upstream addresses; alert on resolver errors.
- Rotate model/provider keys without rebuilding images. Changing
  `JWT_SECRET` signs all users out; changing `INTEGRATION_ENCRYPTION_SECRET`
  requires a planned token re-encryption migration.
- The current Compose stack is a guarded single-host release target, not
  multi-region high availability. Move PostgreSQL to a managed HA service and
  agent state to shared storage before horizontal agent scaling.
