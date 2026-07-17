#!/usr/bin/env bash

# Shared guard for deploy, backup, restore, and rollback. Nested scripts inherit
# the marker and the locked file descriptor from their parent operation.
acquire_teamora_operation_lock() {
  if [[ "${TEAMORA_OPERATION_LOCK_HELD:-0}" == "1" ]]; then
    return
  fi
  if ! command -v flock >/dev/null 2>&1; then
    echo "flock is required for production operations." >&2
    exit 2
  fi
  local lock_file="${TEAMORA_OPERATION_LOCK_FILE:-${PROJECT_ROOT}/.teamora-operation.lock}"
  exec 9>"${lock_file}"
  if ! flock -n 9; then
    echo "Another Teamora deploy/backup/restore/rollback operation is already running." >&2
    exit 2
  fi
  export TEAMORA_OPERATION_LOCK_HELD=1
}

production_env_value() {
  python3 -c \
    'from pathlib import Path; from deploy.check_env import read_env; import sys; print(read_env(Path(sys.argv[1])).get(sys.argv[2], ""))' \
    "$1" "$2"
}
