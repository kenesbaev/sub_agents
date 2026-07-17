#!/usr/bin/env python3
"""Fail-closed validation for Teamora's production environment file."""

from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path
from urllib.parse import urlsplit


REQUIRED = {
    "PUBLIC_ORIGIN",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "DATABASE_URL",
    "JWT_SECRET",
    "INTEGRATION_ENCRYPTION_SECRET",
    "AGENT_INTERNAL_TOKEN",
    "OPENROUTER_API_KEY",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "TRUSTED_HOSTS",
    "CORS_ALLOWED_ORIGINS",
    "AGENT_ALLOWED_ORIGINS",
    "BACKUP_UPLOAD_COMMAND",
}
SECRET_KEYS = {
    "POSTGRES_PASSWORD",
    "JWT_SECRET",
    "INTEGRATION_ENCRYPTION_SECRET",
    "AGENT_INTERNAL_TOKEN",
    "OPENROUTER_API_KEY",
    "GOOGLE_CLIENT_SECRET",
}
CALLBACK_SUFFIXES = ("_REDIRECT_URI", "_CALLBACK_URL")
PLACEHOLDER = re.compile(r"(?:REPLACE_|CHANGE[_-]?ME|YOUR[_-]|EXAMPLE\.COM)", re.IGNORECASE)


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"line {number} does not contain '='")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"line {number} has an invalid variable name")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def exact_https_origin(value: str) -> tuple[bool, str]:
    parsed = urlsplit(value)
    valid = (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
        and parsed.username is None
        and parsed.password is None
    )
    return valid, (parsed.hostname or "").lower()


def main() -> int:
    template_mode = "--template" in sys.argv[1:]
    arguments = [argument for argument in sys.argv[1:] if argument != "--template"]
    path = Path(arguments[0] if arguments else ".env.production")
    if not path.is_file():
        print(f"ERROR: environment file not found: {path}", file=sys.stderr)
        return 2

    try:
        values = read_env(path)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: cannot parse {path}: {exc}", file=sys.stderr)
        return 2

    errors: list[str] = []
    missing = sorted(key for key in REQUIRED if not values.get(key, "").strip())
    if missing:
        errors.append("missing required variables: " + ", ".join(missing))
    if not template_mode:
        for key in sorted(REQUIRED):
            if PLACEHOLDER.search(values.get(key, "")):
                errors.append(f"{key} still contains a placeholder")

    if values.get("APP_ENV", "production").lower() != "production":
        errors.append("APP_ENV must be production")
    if values.get("COOKIE_SECURE", "true").lower() != "true":
        errors.append("COOKIE_SECURE must be true")
    if values.get("AGENT_REQUIRE_AUTH", "true").lower() != "true":
        errors.append("AGENT_REQUIRE_AUTH must be true")
    if values.get("AGENT_CODEX_FALLBACK_ENABLED", "false").lower() != "false":
        errors.append("AGENT_CODEX_FALLBACK_ENABLED must be false")
    if values.get("LOCAL_PASSWORD_AUTH_ENABLED", "false").lower() != "false":
        errors.append("LOCAL_PASSWORD_AUTH_ENABLED must be false")
    if values.get("KALIYA_LINK_FETCH_ENABLED", "false").lower() != "false":
        errors.append("KALIYA_LINK_FETCH_ENABLED must be false")
    if values.get("KALIYA_VIDEO_LINK_DOWNLOAD_ENABLED", "false").lower() != "false":
        errors.append("KALIYA_VIDEO_LINK_DOWNLOAD_ENABLED must be false")
    if values.get("TELEGRAM_AUTO_PUBLISH", "false").lower() != "false":
        errors.append("TELEGRAM_AUTO_PUBLISH must be false")
    if values.get("YOUTUBE_UPLOAD_ENABLED", "false").lower() != "false":
        errors.append("YOUTUBE_UPLOAD_ENABLED must be false")
    if values.get("REQUIRE_OFFSITE_UPLOAD", "1") != "1":
        errors.append("REQUIRE_OFFSITE_UPLOAD must be 1")
    try:
        if int(values.get("ACCESS_TOKEN_MINUTES", "10080")) > 1440:
            errors.append("ACCESS_TOKEN_MINUTES must be 1440 or less")
    except ValueError:
        errors.append("ACCESS_TOKEN_MINUTES must be an integer")
    if values.get("JWT_ALGORITHM", "HS256") not in {"HS256", "HS384", "HS512"}:
        errors.append("JWT_ALGORITHM must be an approved HMAC algorithm")
    if values.get("SCHEDULED_POST_WORKER_BATCH_SIZE", "1") != "1":
        errors.append("SCHEDULED_POST_WORKER_BATCH_SIZE must start at 1")
    expected_ai_limits = {
        "AGENT_TEAM_RATE_COST": "8",
        "AGENT_PROVIDER_MAX_CONCURRENCY": "8",
        "AGENT_PROVIDER_MAX_CONCURRENCY_PER_ACCOUNT": "4",
        "PENDING_TEAM_RUN_MAX_ENTRIES": "1000",
        "PENDING_TEAM_RUN_MAX_PER_ACCOUNT": "20",
        "OPENROUTER_WEB_MAX_RESULTS": "5",
        "OPENROUTER_WEB_MAX_TOTAL_RESULTS": "10",
    }
    for key, expected in expected_ai_limits.items():
        if values.get(key, expected) != expected:
            errors.append(f"{key} must start at the reviewed value {expected}")
    if "NEXT_PUBLIC_API_URL" in values:
        errors.append("NEXT_PUBLIC_API_URL must not be used; browser API calls are same-origin")

    for key, minimum, maximum in (
        ("BACKUP_LOCAL_RETENTION_COUNT", 1, 365),
        ("BACKUP_MIN_FREE_MB", 1024, 1_000_000),
    ):
        try:
            number = int(values.get(key, ""))
            if not minimum <= number <= maximum:
                raise ValueError
        except ValueError:
            errors.append(f"{key} must be an integer from {minimum} to {maximum}")

    if not template_mode and os.name != "nt":
        upload_command = Path(values.get("BACKUP_UPLOAD_COMMAND", ""))
        if not upload_command.is_absolute() or not upload_command.is_file() or not os.access(upload_command, os.X_OK):
            errors.append("BACKUP_UPLOAD_COMMAND must be an executable absolute path")

    public_origin = values.get("PUBLIC_ORIGIN", "").rstrip("/")
    valid_origin, public_host = exact_https_origin(public_origin)
    if not valid_origin:
        errors.append("PUBLIC_ORIGIN must be one exact public HTTPS origin")

    for key in SECRET_KEYS:
        value = values.get(key, "")
        if key not in {"OPENROUTER_API_KEY"} and len(value) < 32:
            errors.append(f"{key} must contain at least 32 characters")

    distinct = [values.get(key, "") for key in ("JWT_SECRET", "INTEGRATION_ENCRYPTION_SECRET", "AGENT_INTERNAL_TOKEN")]
    if len(set(distinct)) != len(distinct):
        errors.append("JWT_SECRET, INTEGRATION_ENCRYPTION_SECRET, and AGENT_INTERNAL_TOKEN must differ")

    for key in ("CORS_ALLOWED_ORIGINS", "AGENT_ALLOWED_ORIGINS"):
        origins = {item.strip().rstrip("/") for item in values.get(key, "").split(",") if item.strip()}
        if "*" in origins or origins != {public_origin}:
            errors.append(f"{key} must contain only PUBLIC_ORIGIN")

    trusted_hosts = {item.strip().lower() for item in values.get("TRUSTED_HOSTS", "").split(",") if item.strip()}
    if "*" in trusted_hosts:
        errors.append("TRUSTED_HOSTS cannot contain a wildcard")
    if public_host and public_host not in trusted_hosts:
        errors.append("TRUSTED_HOSTS must include the PUBLIC_ORIGIN hostname")

    for key in ("DATABASE_URL",):
        parsed = urlsplit(values.get(key, ""))
        if not parsed.scheme or not parsed.hostname:
            errors.append(f"{key} must be an absolute connection URL")
        elif parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
            errors.append(f"{key} must use the private service hostname, not loopback")
        elif parsed.hostname != "postgres":
            errors.append("DATABASE_URL must use the private postgres service hostname")

    parsed_database = urlsplit(values.get("DATABASE_URL", ""))
    if parsed_database.username != values.get("POSTGRES_USER") or parsed_database.path.lstrip("/") != values.get("POSTGRES_DB"):
        errors.append("DATABASE_URL user/database must match POSTGRES_USER and POSTGRES_DB")

    bind_address = values.get("HTTP_BIND_ADDRESS", "127.0.0.1").strip().lower()
    if bind_address not in {"127.0.0.1", "::1", "localhost"}:
        errors.append("HTTP_BIND_ADDRESS must remain loopback behind the TLS edge")

    for key in (
        "DATABASE_AUTO_CREATE_SCHEMA",
        "DATABASE_STARTUP_BACKFILL",
        "YOUTUBE_SNAPSHOT_WORKER_RUN_IN_API",
    ):
        if values.get(key, "false").lower() != "false":
            errors.append(f"{key} must be false")

    google_paths = {
        "GOOGLE_REDIRECT_URI": "/api/auth/google/callback",
        "GOOGLE_CONNECTED_REDIRECT_URI": "/api/connected-apps/google/callback",
    }
    for key, expected_path in google_paths.items():
        parsed = urlsplit(values.get(key, ""))
        if parsed.path != expected_path or parsed.query or parsed.fragment:
            errors.append(f"{key} must use the exact callback path {expected_path}")

    for key, value in values.items():
        if not value or not key.endswith(CALLBACK_SUFFIXES):
            continue
        parsed = urlsplit(value)
        callback_origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        if parsed.scheme != "https" or callback_origin != public_origin:
            errors.append(f"{key} must use PUBLIC_ORIGIN and HTTPS")

    if os.name != "nt" and not template_mode:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            errors.append("environment file permissions are too broad; run chmod 600")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Production environment check failed with {len(errors)} error(s).", file=sys.stderr)
        return 1

    print("Production environment check passed (secret values were not printed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
