from __future__ import annotations

from pydantic import BaseModel


class CreateConversationResponse(BaseModel):
    id: str
    created_at: str


class ChatMessageRequest(BaseModel):
    conversation_id: str
    message: str

