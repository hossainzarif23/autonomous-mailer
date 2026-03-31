from __future__ import annotations

from pydantic import BaseModel


class AuthenticatedUser(BaseModel):
    id: str
    email: str
    name: str | None = None
    picture_url: str | None = None
    gmail_scope_granted: bool = False
