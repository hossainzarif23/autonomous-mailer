from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: str
    type: str
    title: str
    body: str | None
    metadata: dict[str, Any]
    is_read: bool
    created_at: str

