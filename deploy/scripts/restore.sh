#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
cd "${PROJECT_ROOT}"
source "${SCRIPT_DIR}/_lib.sh"
acquire_teamora_operation_lock

BACKUP_FILE="${1:-}"
ENV_FILE="${2:-.env.production}"
COMPOSE=(docker compose --env-file "${ENV_FILE}" -f compose.production.yml)
BACKUP_NAME="$(basename "${BACKUP_FILE}")"
BACKUP_STAMP="${BACKUP_NAME#teamora-postgres-}"
BACKUP_STAMP="${BACKUP_STAMP%.dump}"
AGENT_BACKUP_FILE="${AGENT_BACKUP_FILE:-$(dirname "${BACKUP_FILE}")/teamora-agent-data-${BACKUP_STAMP}.tar.gz}"

if [[ -z "${BACKUP_FILE}" || ! -f "${BACKUP_FILE}" ]]; then
  echo "Usage: CONFIRM_RESTORE=YES bash deploy/scripts/restore.sh BACKUP.dump [.env.production]" >&2
  exit 2
fi
if [[ "${CONFIRM_RESTORE:-}" != "YES" ]]; then
  echo "Restore replaces the production public schema. Set CONFIRM_RESTORE=YES after checking the target." >&2
  exit 2
fi
if [[ ! -f "${AGENT_BACKUP_FILE}" ]]; then
  echo "Matching agent-data archive not found: ${AGENT_BACKUP_FILE}" >&2
  exit 2
fi

if [[ -f "${BACKUP_FILE}.sha256" ]]; then
  (
    cd "$(dirname "${BACKUP_FILE}")"
    sha256sum --check "$(basename "${BACKUP_FILE}").sha256"
  )
else
  echo "WARNING: no checksum file was found; verify backup provenance before continuing." >&2
fi
if [[ -f "${AGENT_BACKUP_FILE}.sha256" ]]; then
  (
    cd "$(dirname "${AGENT_BACKUP_FILE}")"
    sha256sum --check "$(basename "${AGENT_BACKUP_FILE}").sha256"
  )
else
  echo "WARNING: no agent-data checksum was found." >&2
fi

python3 deploy/check_env.py "${ENV_FILE}"
"${COMPOSE[@]}" up -d --wait postgres

echo "Creating a safety backup before restore..."
# Do not let retention delete the older backup selected as the restore source.
SKIP_LOCAL_BACKUP_PRUNE=1 bash deploy/scripts/backup.sh "${ENV_FILE}"

# Re-validate both selected artifacts immediately before any destructive step.
test -f "${BACKUP_FILE}" -a -f "${AGENT_BACKUP_FILE}"
(
  cd "$(dirname "${BACKUP_FILE}")"
  sha256sum --check "$(basename "${BACKUP_FILE}").sha256"
)
(
  cd "$(dirname "${AGENT_BACKUP_FILE}")"
  sha256sum --check "$(basename "${AGENT_BACKUP_FILE}").sha256"
)
"${COMPOSE[@]}" exec -T postgres pg_restore --list < "${BACKUP_FILE}" >/dev/null
"${COMPOSE[@]}" run --rm --no-deps --entrypoint python agent -c \
  "import sys,tarfile; archive=tarfile.open(fileobj=sys.stdin.buffer,mode='r|gz'); members=list(archive); archive.close(); assert members and all(m.name == 'data' or m.name.startswith('data/') for m in members)" \
  < "${AGENT_BACKUP_FILE}"

echo "Stopping application traffic..."
"${COMPOSE[@]}" stop nginx frontend agent backend youtube-worker scheduled-post-worker

echo "Replacing the public schema..."
"${COMPOSE[@]}" exec -T postgres sh -ec \
  'psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --set=ON_ERROR_STOP=1 --command="DROP SCHEMA public CASCADE; CREATE SCHEMA public;"'
"${COMPOSE[@]}" exec -T postgres sh -ec \
  'exec pg_restore --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --exit-on-error --no-owner --no-acl' \
  < "${BACKUP_FILE}"

echo "Restoring agent memory volume..."
"${COMPOSE[@]}" run --rm --no-deps --entrypoint python agent -c \
  "import shutil,sys,tarfile; from pathlib import Path; root=Path('/app/data'); [(shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()) for p in list(root.iterdir())]; archive=tarfile.open(fileobj=sys.stdin.buffer,mode='r|gz'); archive.extractall('/app',filter='data'); archive.close()" \
  < "${AGENT_BACKUP_FILE}"

echo "Applying forward migrations and restarting services..."
"${COMPOSE[@]}" run --rm migrate
"${COMPOSE[@]}" up -d --wait
"${COMPOSE[@]}" exec -T backend python -c \
  "import os,urllib.request; from urllib.parse import urlsplit; request=urllib.request.Request('http://127.0.0.1:8000/readyz',headers={'Host':urlsplit(os.environ['BACKEND_URL']).netloc}); urllib.request.urlopen(request,timeout=5)"

echo "Restore completed. Perform the authenticated smoke checks in deploy/PRODUCTION.md."
