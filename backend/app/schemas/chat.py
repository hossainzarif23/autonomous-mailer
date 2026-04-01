from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class CreateConversationResponse(BaseModel):
    id: str
    created_at: str


class ConversationSummary(BaseModel):
    id: str
    title: str | None
    created_at: str
    updated_at: str


class ChatMessageRequest(BaseModel):
    conversation_id: str
    message: str


class ChatMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    content_blocks: list[dict[str, Any]] | None = None
    status: str | None = None
    turn_id: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: str
