from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ApprovalRequest(BaseModel):
    action: Literal["approve", "edit", "reject"]
    edited_to: str | None = None
    edited_subject: str | None = None
    edited_body: str | None = None
    feedback: str | None = None


class ApprovalResponse(BaseModel):
    success: bool
    status: str
    gmail_message_id: str | None = None
