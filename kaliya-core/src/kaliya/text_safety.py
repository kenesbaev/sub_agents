from __future__ import annotations

import re


def contains_secret_like_text(*values: object) -> bool:
    text = " ".join(str(value or "") for value in values)
    return any(pattern.search(text) for pattern in SECRET_LIKE_PATTERNS)


def redact_sensitive_text(text: str) -> str:
    redacted = SECRET_ASSIGNMENT_RE.sub(r"\1=<redacted>", text)
    redacted = BEARER_SECRET_RE.sub("Bearer <redacted>", redacted)
    redacted = OPENAI_KEY_RE.sub("sk-<redacted>", redacted)
    redacted = TELEGRAM_TOKEN_RE.sub("<redacted-telegram-token>", redacted)
    redacted = AWS_ACCESS_KEY_RE.sub("<redacted-aws-access-key>", redacted)
    return PRIVATE_KEY_BLOCK_RE.sub("-----BEGIN <redacted-private-key>-----", redacted)


SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|cookie|password|passwd|secret|token)\b"
    r"\s*[:=]\s*([^\s,;]+)"
)
BEARER_SECRET_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")
OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}")
TELEGRAM_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")
PRIVATE_KEY_BLOCK_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
AWS_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
SECRET_LIKE_PATTERNS = (
    SECRET_ASSIGNMENT_RE,
    BEARER_SECRET_RE,
    OPENAI_KEY_RE,
    TELEGRAM_TOKEN_RE,
    PRIVATE_KEY_BLOCK_RE,
    AWS_ACCESS_KEY_RE,
)
