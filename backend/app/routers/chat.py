from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import AgentContext
from app.agents.coordinator import get_coordinator_agent
from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.conversation import Conversation
from app.models.user import User
from app.schemas.chat import ChatMessageRequest, ChatMessageResponse, ConversationSummary, CreateConversationResponse
from app.services.auth_service import get_valid_access_token
from app.services.gmail_service import GmailService
from app.services.hitl_service import is_hitl_interrupt, persist_hitl_interrupts
from app.services.notification_service import notification_service

router = APIRouter()


def _iso(value: datetime | None) -> str:
    if value is None:
        return datetime.now(UTC).isoformat()
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
        return "".join(parts)
    return str(content)


def _serialize_checkpoint_message(message: BaseMessage, index: int) -> ChatMessageResponse | None:
    if isinstance(message, HumanMessage):
        role = "user"
    elif isinstance(message, AIMessage):
        role = "assistant"
    else:
        return None

    return ChatMessageResponse(
        id=f"checkpoint-{index}",
        role=role,
        content=_message_text(message.content),
        created_at=datetime.now(UTC).isoformat(),
    )


def _serialize_conversation(conversation: Conversation) -> ConversationSummary:
    return ConversationSummary(
        id=str(conversation.id),
        title=conversation.title,
        created_at=_iso(conversation.created_at),
        updated_at=_iso(conversation.updated_at),
    )


def _sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data)}\n\n"


async def _get_owned_conversation(db: AsyncSession, conversation_id: str, user_id: uuid.UUID) -> Conversation:
    conversation = await db.get(Conversation, uuid.UUID(conversation_id))
    if conversation is None or conversation.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


@router.post("/conversations", response_model=CreateConversationResponse)
async def create_conversation(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conversation = Conversation(user_id=current_user.id)
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return CreateConversationResponse(id=str(conversation.id), created_at=_iso(conversation.created_at))


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.scalars(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(desc(Conversation.updated_at), desc(Conversation.created_at))
    )
    return [_serialize_conversation(conversation) for conversation in result.all()]


@router.get("/history/{conversation_id}", response_model=list[ChatMessageResponse])
async def get_history(
    conversation_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_conversation(db, conversation_id, current_user.id)
    checkpoint_tuple = await request.app.state.checkpointer.aget_tuple({"configurable": {"thread_id": conversation_id}})
    if checkpoint_tuple is None:
        return []

    messages = checkpoint_tuple.checkpoint.get("channel_values", {}).get("messages", [])
    serialized: list[ChatMessageResponse] = []
    for index, message in enumerate(messages):
        item = _serialize_checkpoint_message(message, index)
        if item is not None and item.content.strip():
            serialized.append(item)
    return serialized


@router.post("/message")
async def stream_chat_message(
    payload: ChatMessageRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conversation = await _get_owned_conversation(db, payload.conversation_id, current_user.id)

    if conversation.title is None:
        conversation.title = payload.message.strip()[:80] or "New conversation"
    conversation.updated_at = datetime.now(UTC)
    await db.commit()

    async def event_stream():
        try:
            access_token = await get_valid_access_token(str(current_user.id), db)
            context = AgentContext(
                user_id=str(current_user.id),
                conversation_id=payload.conversation_id,
                gmail_service=GmailService(access_token),
                db_session=db,
                notification_service=notification_service,
            )
            coordinator = get_coordinator_agent(request.app.state.checkpointer)
            config = {"configurable": {"thread_id": payload.conversation_id}}

            async for part in coordinator.astream(
                {"messages": [HumanMessage(content=payload.message)]},
                config=config,
                context=context,
                stream_mode=["messages", "updates"],
                version="v2",
            ):
                if part["type"] == "messages":
                    chunk, _metadata = part["data"]
                    text = _message_text(chunk.content)
                    if text:
                        yield _sse({"type": "token", "content": text})
                elif part["type"] == "updates":
                    updates = part["data"]
                    interrupts = updates.get("__interrupt__", ())
                    for interrupt in interrupts:
                        interrupt_value = getattr(interrupt, "value", interrupt)
                        if is_hitl_interrupt(interrupt_value):
                            events = await persist_hitl_interrupts(
                                db,
                                user_id=str(current_user.id),
                                conversation_id=payload.conversation_id,
                                interrupt_value=interrupt_value,
                                notification_service=notification_service,
                            )
                            for event in events:
                                yield _sse(
                                    {
                                        "type": "approval_pending",
                                        "draft_id": event.get("draft_id"),
                                    }
                                )
            yield _sse({"type": "done"})
        except Exception as exc:
            yield _sse({"type": "error", "content": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
