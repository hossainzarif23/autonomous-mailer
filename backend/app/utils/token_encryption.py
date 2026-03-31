from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


@lru_cache
def get_fernet() -> Fernet:
    if not settings.TOKEN_ENCRYPTION_KEY:
        raise ValueError("TOKEN_ENCRYPTION_KEY is not configured.")
    return Fernet(settings.TOKEN_ENCRYPTION_KEY.encode())


def encrypt_token(token: str) -> str:
    return get_fernet().encrypt(token.encode()).decode()


def decrypt_token(token: str) -> str:
    try:
        return get_fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Stored token could not be decrypted.") from exc
