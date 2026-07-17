#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
cd "${PROJECT_ROOT}"
source "${SCRIPT_DIR}/_lib.sh"
acquire_teamora_operation_lock

ENV_FILE="${1:-.env.production}"
ROLLBACK_IMAGE_TAG="${ROLLBACK_IMAGE_TAG:-}"

if [[ -z "${ROLLBACK_IMAGE_TAG}" ]]; then
  echo "Set ROLLBACK_IMAGE_TAG to the previously tested immutable tag." >&2
  exit 2
fi
if [[ "${CONFIRM_ROLLBACK:-}" != "YES" ]]; then
  echo "Set CONFIRM_ROLLBACK=YES after verifying database compatibility." >&2
  exit 2
fi

BASE_COMPOSE=(docker compose --env-file "${ENV_FILE}" -f compose.production.yml)
ROLLBACK_COMPOSE=(env IMAGE_TAG="${ROLLBACK_IMAGE_TAG}" docker compose --env-file "${ENV_FILE}" -f compose.production.yml)

python3 deploy/check_env.py "${ENV_FILE}"
bash deploy/scripts/backup.sh "${ENV_FILE}"

if [[ "${ROLLBACK_PULL:-0}" == "1" ]]; then
  "${ROLLBACK_COMPOSE[@]}" pull backend agent frontend
fi

# --no-deps deliberately avoids running an older migration image against a
# newer schema. Only use this for a release documented as schema-compatible.
echo "Draining traffic and writers before replacing application images..."
"${BASE_COMPOSE[@]}" stop nginx frontend agent backend youtube-worker scheduled-post-worker
"${ROLLBACK_COMPOSE[@]}" up -d --wait --no-deps backend agent youtube-worker scheduled-post-worker frontend
"${BASE_COMPOSE[@]}" up -d --wait --no-deps nginx
"${BASE_COMPOSE[@]}" exec -T backend python -c \
  "import os,urllib.request; from urllib.parse import urlsplit; request=urllib.request.Request('http://127.0.0.1:8000/readyz',headers={'Host':urlsplit(os.environ['BACKEND_URL']).netloc}); urllib.request.urlopen(request,timeout=5)"
"${BASE_COMPOSE[@]}" exec -T agent python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4173/readyz', timeout=5)"

echo "Application rollback to ${ROLLBACK_IMAGE_TAG} passed container checks. Run authenticated smoke tests now."
