#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
cd "${PROJECT_ROOT}"
source "${SCRIPT_DIR}/_lib.sh"
acquire_teamora_operation_lock

ENV_FILE="${1:-.env.production}"
COMPOSE=(docker compose --env-file "${ENV_FILE}" -f compose.production.yml)

python3 deploy/check_env.py "${ENV_FILE}"
"${COMPOSE[@]}" config --quiet

if [[ "${SKIP_BACKUP:-0}" != "1" ]] \
  && "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx postgres; then
  bash deploy/scripts/backup.sh "${ENV_FILE}"
fi

echo "Building immutable application images..."
"${COMPOSE[@]}" build --pull backend agent frontend

echo "Starting data services and applying migrations..."
"${COMPOSE[@]}" up -d --wait postgres
echo "Draining public traffic and all database writers before migration..."
"${COMPOSE[@]}" stop nginx frontend agent backend youtube-worker scheduled-post-worker
RELEASE_PENDING=1
trap 'if [[ "${RELEASE_PENDING:-0}" == "1" ]]; then echo "Migration/deploy failed; public traffic and writers may remain stopped for safe recovery." >&2; fi' ERR
"${COMPOSE[@]}" run --rm migrate

echo "Starting the production stack..."
"${COMPOSE[@]}" up -d --wait

"${COMPOSE[@]}" exec -T backend python -c \
  "import os,urllib.request; from urllib.parse import urlsplit; request=urllib.request.Request('http://127.0.0.1:8000/readyz',headers={'Host':urlsplit(os.environ['BACKEND_URL']).netloc}); urllib.request.urlopen(request,timeout=5)"
"${COMPOSE[@]}" exec -T agent python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4173/readyz', timeout=5)"
"${COMPOSE[@]}" exec -T nginx wget -qO- http://127.0.0.1/nginx-health >/dev/null
RELEASE_PENDING=0
trap - ERR

echo "Deployment health checks passed. Complete the authenticated and provider canaries in deploy/PRODUCTION.md."
