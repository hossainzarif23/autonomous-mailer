from __future__ import annotations

from urllib.parse import quote

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.schemas.auth import AuthenticatedUser
from app.services.auth_service import (
    build_jwt_for_user,
    build_oauth_scopes,
    compute_token_expiry,
    fetch_google_userinfo,
    gmail_scopes_granted,
)
from app.utils.token_encryption import encrypt_token

router = APIRouter()

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": build_oauth_scopes(),
    },
)


def serialize_user(user: User) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=str(user.id),
        email=user.email,
        name=user.name,
        picture_url=user.picture_url,
        gmail_scope_granted=user.gmail_scope_granted,
    )


@router.get("/login")
async def login(request: Request):
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Google OAuth is not configured")

    return await oauth.google.authorize_redirect(
        request,
        settings.GOOGLE_REDIRECT_URI,
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )


@router.get("/callback")
async def auth_callback(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as exc:
        error_message = quote(str(exc))
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error={error_message}", status_code=302)

    access_token = token.get("access_token")
    if not access_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google did not return an access token")

    userinfo = await fetch_google_userinfo(access_token)
    google_id = userinfo.get("sub")
    email = userinfo.get("email")
    if not google_id or not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google user info is incomplete")

    existing = await db.scalar(select(User).where(User.google_id == google_id))
    if existing is None:
        existing = await db.scalar(select(User).where(User.email == email))

    if existing is None:
        user = User(
            google_id=google_id,
            email=email,
            name=userinfo.get("name"),
            picture_url=userinfo.get("picture"),
            access_token=encrypt_token(access_token),
            refresh_token=encrypt_token(token["refresh_token"]) if token.get("refresh_token") else None,
            token_expiry=compute_token_expiry(token),
            gmail_scope_granted=gmail_scopes_granted(token.get("scope")),
        )
        db.add(user)
    else:
        user = existing
        user.google_id = google_id
        user.email = email
        user.name = userinfo.get("name")
        user.picture_url = userinfo.get("picture")
        user.access_token = encrypt_token(access_token)
        if token.get("refresh_token"):
            user.refresh_token = encrypt_token(token["refresh_token"])
        user.token_expiry = compute_token_expiry(token)
        user.gmail_scope_granted = gmail_scopes_granted(token.get("scope"))

    await db.commit()
    await db.refresh(user)

    response = RedirectResponse(url=f"{settings.FRONTEND_URL}/dashboard", status_code=302)
    response.set_cookie(
        key="access_token",
        value=build_jwt_for_user(str(user.id)),
        httponly=True,
        secure=settings.APP_ENV != "development",
        samesite="lax",
        max_age=settings.JWT_EXPIRY_HOURS * 3600,
        path="/",
    )
    return response


@router.post("/logout")
async def logout():
    response = JSONResponse({"success": True})
    response.delete_cookie(key="access_token", path="/")
    return response


@router.get("/me", response_model=AuthenticatedUser)
async def me(current_user: User = Depends(get_current_user)):
    return serialize_user(current_user)
