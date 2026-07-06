from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status

from app.config import get_settings


def integration_fernet() -> Fernet:
    settings = get_settings()
    secret = settings.integration_encryption_secret or settings.jwt_secret
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_token(token: str) -> str:
    return integration_fernet().encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_token(value: str) -> str:
    try:
        return integration_fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Integration token cannot be decrypted",
        ) from exc
