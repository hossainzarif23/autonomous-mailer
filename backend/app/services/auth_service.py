from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User
from app.utils.token_encryption import decrypt_token, encrypt_token

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GMAIL_READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


def build_jwt_for_user(user_id: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.JWT_EXPIRY_HOURS)).timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def build_oauth_scopes() -> str:
    return " ".join(
        [
            "openid",
            "email",
            "profile",
            GMAIL_READ_SCOPE,
            GMAIL_SEND_SCOPE,
        ]
    )


def compute_token_expiry(token_payload: dict[str, Any]) -> datetime | None:
    expires_at = token_payload.get("expires_at")
    if expires_at is not None:
        return datetime.fromtimestamp(float(expires_at), tz=UTC)

    expires_in = token_payload.get("expires_in")
    if expires_in is not None:
        return datetime.now(UTC) + timedelta(seconds=int(expires_in))

    return None


def gmail_scopes_granted(scope_value: str | None) -> bool:
    if not scope_value:
        return False
    scopes = set(scope_value.split())
    return GMAIL_READ_SCOPE in scopes and GMAIL_SEND_SCOPE in scopes


async def fetch_google_userinfo(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()


async def refresh_google_access_token(refresh_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
        return response.json()


async def get_valid_access_token(user_id: str, db: AsyncSession) -> str:
    user = await db.get(User, user_id)
    if user is None:
        raise ValueError("User not found.")

    if user.token_expiry and user.token_expiry.tzinfo is None:
        user.token_expiry = user.token_expiry.replace(tzinfo=UTC)

    now = datetime.now(UTC)
    if user.token_expiry and user.token_expiry > now + timedelta(minutes=5):
        return decrypt_token(user.access_token)

    if not user.refresh_token:
        return decrypt_token(user.access_token)

    refreshed = await refresh_google_access_token(decrypt_token(user.refresh_token))
    access_token = refreshed["access_token"]

    user.access_token = encrypt_token(access_token)
    user.token_expiry = compute_token_expiry(refreshed)
    if refreshed.get("refresh_token"):
        user.refresh_token = encrypt_token(refreshed["refresh_token"])
    if refreshed.get("scope"):
        user.gmail_scope_granted = gmail_scopes_granted(refreshed.get("scope"))

    await db.commit()
    await db.refresh(user)
    return access_token
