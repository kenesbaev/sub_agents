#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
cd "${PROJECT_ROOT}"
source "${SCRIPT_DIR}/_lib.sh"
acquire_teamora_operation_lock

ENV_FILE="${1:-.env.production}"
BACKUP_DIR="${BACKUP_DIR:-${PROJECT_ROOT}/backups}"
FILE_UPLOAD_COMMAND="$(production_env_value "${ENV_FILE}" BACKUP_UPLOAD_COMMAND)"
FILE_RETENTION_COUNT="$(production_env_value "${ENV_FILE}" BACKUP_LOCAL_RETENTION_COUNT)"
FILE_MIN_FREE_MB="$(production_env_value "${ENV_FILE}" BACKUP_MIN_FREE_MB)"
FILE_REQUIRE_OFFSITE="$(production_env_value "${ENV_FILE}" REQUIRE_OFFSITE_UPLOAD)"
BACKUP_UPLOAD_COMMAND="${BACKUP_UPLOAD_COMMAND:-${FILE_UPLOAD_COMMAND}}"
BACKUP_LOCAL_RETENTION_COUNT="${BACKUP_LOCAL_RETENTION_COUNT:-${FILE_RETENTION_COUNT:-7}}"
BACKUP_MIN_FREE_MB="${BACKUP_MIN_FREE_MB:-${FILE_MIN_FREE_MB:-10240}}"
REQUIRE_OFFSITE_UPLOAD="${REQUIRE_OFFSITE_UPLOAD:-${FILE_REQUIRE_OFFSITE:-1}}"
COMPOSE=(docker compose --env-file "${ENV_FILE}" -f compose.production.yml)
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="${BACKUP_DIR}/teamora-postgres-${STAMP}.dump"
TEMP="${TARGET}.partial"
AGENT_TARGET="${BACKUP_DIR}/teamora-agent-data-${STAMP}.tar.gz"
AGENT_TEMP="${AGENT_TARGET}.partial"
AGENT_WAS_RUNNING=0

if [[ ! "${BACKUP_LOCAL_RETENTION_COUNT}" =~ ^[1-9][0-9]*$ ]] \
  || (( BACKUP_LOCAL_RETENTION_COUNT > 365 )); then
  echo "BACKUP_LOCAL_RETENTION_COUNT must be an integer from 1 to 365." >&2
  exit 2
fi
if [[ ! "${BACKUP_MIN_FREE_MB}" =~ ^[1-9][0-9]*$ ]] || (( BACKUP_MIN_FREE_MB < 1024 )); then
  echo "BACKUP_MIN_FREE_MB must be an integer of at least 1024." >&2
  exit 2
fi

prune_uploaded_local_backups() {
  shopt -s nullglob
  local dumps=("${BACKUP_DIR}"/teamora-postgres-*.dump)
  local excess=$(( ${#dumps[@]} - BACKUP_LOCAL_RETENTION_COUNT ))
  if (( excess <= 0 )); then
    return
  fi
  local index dump name stamp agent_archive
  for (( index=0; index<excess; index++ )); do
    dump="${dumps[index]}"
    name="$(basename -- "${dump}")"
    if [[ ! "${name}" =~ ^teamora-postgres-([0-9]{8}T[0-9]{6}Z)\.dump$ ]]; then
      continue
    fi
    stamp="${BASH_REMATCH[1]}"
    agent_archive="${BACKUP_DIR}/teamora-agent-data-${stamp}.tar.gz"
    rm -f -- "${dump}" "${dump}.sha256" "${agent_archive}" "${agent_archive}.sha256"
  done
  echo "Local backup retention kept the newest ${BACKUP_LOCAL_RETENTION_COUNT} uploaded backup sets."
}

restore_agent() {
  if [[ "${AGENT_WAS_RUNNING}" == "1" ]]; then
    "${COMPOSE[@]}" start agent >/dev/null 2>&1 || true
  fi
  rm -f "${TEMP}" "${AGENT_TEMP}"
}
trap restore_agent EXIT

umask 077
mkdir -p "${BACKUP_DIR}"
rm -f "${TEMP}" "${AGENT_TEMP}"

AVAILABLE_KB="$(df -Pk "${BACKUP_DIR}" | awk 'NR==2 {print $4}')"
if [[ ! "${AVAILABLE_KB}" =~ ^[0-9]+$ ]] || (( AVAILABLE_KB < BACKUP_MIN_FREE_MB * 1024 )); then
  echo "Backup aborted: less than ${BACKUP_MIN_FREE_MB} MiB is free in ${BACKUP_DIR}." >&2
  exit 1
fi

echo "Creating a consistent PostgreSQL custom-format backup..."
"${COMPOSE[@]}" exec -T postgres sh -ec \
  'exec pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --compress=6 --no-owner --no-acl' \
  > "${TEMP}"

test -s "${TEMP}"
mv "${TEMP}" "${TARGET}"
(
  cd "${BACKUP_DIR}"
  sha256sum "$(basename "${TARGET}")" > "$(basename "${TARGET}").sha256"
)
chmod 600 "${TARGET}" "${TARGET}.sha256"

if "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx agent; then
  AGENT_WAS_RUNNING=1
  echo "Briefly stopping Agent API for a consistent agent-data archive..."
  "${COMPOSE[@]}" stop -t 30 agent
fi
"${COMPOSE[@]}" run --rm --no-deps --entrypoint python agent -c \
  "import sys,tarfile; archive=tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz'); archive.add('/app/data',arcname='data'); archive.close()" \
  > "${AGENT_TEMP}"
test -s "${AGENT_TEMP}"
mv "${AGENT_TEMP}" "${AGENT_TARGET}"
(
  cd "${BACKUP_DIR}"
  sha256sum "$(basename "${AGENT_TARGET}")" > "$(basename "${AGENT_TARGET}").sha256"
)
chmod 600 "${AGENT_TARGET}" "${AGENT_TARGET}.sha256"
if [[ "${AGENT_WAS_RUNNING}" == "1" ]]; then
  "${COMPOSE[@]}" start agent
  AGENT_WAS_RUNNING=0
fi

echo "Backups created: ${TARGET} and ${AGENT_TARGET}"
if [[ -n "${BACKUP_UPLOAD_COMMAND:-}" ]]; then
  if [[ ! -x "${BACKUP_UPLOAD_COMMAND}" ]]; then
    echo "BACKUP_UPLOAD_COMMAND must be an executable absolute path." >&2
    exit 1
  fi
  "${BACKUP_UPLOAD_COMMAND}" "${TARGET}" "${TARGET}.sha256" "${AGENT_TARGET}" "${AGENT_TARGET}.sha256"
  echo "Off-site upload hook completed."
  if [[ "${SKIP_LOCAL_BACKUP_PRUNE:-0}" != "1" ]]; then
    prune_uploaded_local_backups
  fi
elif [[ "${REQUIRE_OFFSITE_UPLOAD:-1}" == "1" ]]; then
  echo "Local backup exists, but off-site upload is required. Set BACKUP_UPLOAD_COMMAND to a trusted executable." >&2
  exit 1
else
  echo "WARNING: off-site upload was not enforced for this run." >&2
fi
trap - EXIT
