from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ApprovalRequest(BaseModel):
    action: Literal["approve", "edit_and_approve", "reject"]
    edited_to: str | None = None
    edited_subject: str | None = None
    edited_body: str | None = None

