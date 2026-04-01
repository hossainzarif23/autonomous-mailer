from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import AgentContext
from app.agents.coordinator import get_coordinator_agent
from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.conversation import Conversation
from app.models.email_draft import EmailDraft
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


def _serialize_conversation(conversation: Conversation) -> ConversationSummary:
    return ConversationSummary(
        id=str(conversation.id),
        title=conversation.title,
        created_at=_iso(conversation.created_at),
        updated_at=_iso(conversation.updated_at),
    )


def _sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _markdown_block(content: str) -> dict[str, Any]:
    return {"type": "markdown", "content": content}


def _status_block(label: str, tone: str = "neutral", detail: str | None = None) -> dict[str, Any]:
    return {
        "type": "status",
        "label": label,
        "tone": tone,
        "detail": detail,
    }


def _tool_action_block(label: str, state: str = "complete", detail: str | None = None) -> dict[str, Any]:
    return {
        "type": "tool_action",
        "label": label,
        "state": state,
        "detail": detail,
    }


def _email_list_block(title: str, emails: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "email_list",
        "title": title,
        "emails": emails,
    }


def _summary_block(title: str, content: str) -> dict[str, Any]:
    return {
        "type": "summary",
        "title": title,
        "content": content,
    }


def _research_report_block(title: str, content: str) -> dict[str, Any]:
    return {
        "type": "research_report",
        "title": title,
        "content": content,
    }


def _draft_block(draft: EmailDraft) -> dict[str, Any]:
    status_map = {
        "pending_approval": "waiting_approval",
        "rejected": "rewrite_requested",
        "sent": "sent",
        "send_failed": "error",
    }
    return {
        "type": "draft_email",
        "draft_id": str(draft.id),
        "to": draft.edited_to or draft.to_address,
        "subject": draft.edited_subject or draft.subject,
        "body_preview": draft.edited_body or draft.body,
        "draft_type": draft.draft_type,
        "approval_state": status_map.get(draft.status, "draft_ready"),
        "conversation_id": str(draft.conversation_id) if draft.conversation_id else None,
    }


def _append_markdown(blocks: list[dict[str, Any]], content: str):
    text = content.strip()
    if not text:
        return
    if blocks and blocks[-1]["type"] == "markdown":
        blocks[-1]["content"] = f"{blocks[-1]['content']}\n\n{text}".strip()
    else:
        blocks.append(_markdown_block(text))


def _parse_email_entries(raw: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ". Subject:" in line and line.split(". ", 1)[0].isdigit():
            if current:
                entries.append(current)
            current = {
                "subject": line.split("Subject:", 1)[1].strip(),
                "from_name": "",
                "from_email": "",
                "date": "",
                "message_id": "",
                "thread_id": "",
                "snippet": "",
            }
            continue
        if current is None:
            continue
        if line.startswith("From:"):
            sender = line.split("From:", 1)[1].strip()
            if "<" in sender and ">" in sender:
                name, email = sender.rsplit("<", 1)
                current["from_name"] = name.strip()
                current["from_email"] = email.rstrip(">").strip()
            else:
                current["from_name"] = sender
                current["from_email"] = sender
        elif line.startswith("Date:"):
            current["date"] = line.split("Date:", 1)[1].strip()
        elif line.startswith("Message ID:"):
            current["message_id"] = line.split("Message ID:", 1)[1].strip()
        elif line.startswith("Thread ID:"):
            current["thread_id"] = line.split("Thread ID:", 1)[1].strip()
        elif line.startswith("Snippet:"):
            current["snippet"] = line.split("Snippet:", 1)[1].strip()

    if current:
        entries.append(current)

    return entries


def _parse_mail_reader_payload(content: str) -> tuple[str, list[dict[str, Any]], str | None]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return content.strip(), [], None

    summary = str(payload.get("summary") or "").strip()
    title: str | None = None
    emails: list[dict[str, Any]] = []
    for output in payload.get("tool_outputs", []):
        if not isinstance(output, dict):
            continue
        name = str(output.get("name") or "")
        raw_output = str(output.get("content") or "")
        parsed = _parse_email_entries(raw_output)
        if parsed:
            emails = parsed
            if name == "get_recent_emails":
                title = "Recent Emails"
            elif name == "search_emails_by_sender":
                title = "Emails From Sender"
            elif name == "search_emails_by_topic":
                title = "Topic Search Results"
            elif name == "get_email_thread":
                title = "Thread Messages"
            else:
                title = "Email Results"
            break
        if name == "get_full_email" and raw_output.strip():
            title = "Email Detail"
            summary = summary or raw_output.strip()

    return summary, emails, title


def _parse_research_payload(content: str) -> str:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return content.strip()
    return str(payload.get("summary") or content).strip()


def _content_from_blocks(blocks: list[dict[str, Any]]) -> str:
    markdown_parts = [block["content"] for block in blocks if block.get("type") == "markdown" and block.get("content")]
    return "\n\n".join(markdown_parts).strip()


def _build_user_message(message: HumanMessage, index: int) -> ChatMessageResponse:
    content = _message_text(message.content).strip()
    return ChatMessageResponse(
        id=f"human-{index}",
        role="user",
        content=content,
        content_blocks=[_markdown_block(content)],
        status="complete",
        created_at=datetime.now(UTC).isoformat(),
    )


def _start_assistant_turn(index: int) -> dict[str, Any]:
    return {
        "id": f"assistant-{index}",
        "role": "assistant",
        "content_blocks": [],
        "status": "complete",
        "turn_id": f"turn-{index}",
        "created_at": datetime.now(UTC).isoformat(),
        "draft_slots": 0,
    }


def _label_for_tool(name: str) -> str:
    labels = {
        "call_mail_reader": "Inbox reviewed",
        "call_web_search": "Research completed",
        "call_mailing_agent": "Draft generated",
        "send_email": "Email sent",
    }
    return labels.get(name, name.replace("_", " ").title())


def _apply_tool_message_to_turn(turn: dict[str, Any], message: ToolMessage):
    blocks: list[dict[str, Any]] = turn["content_blocks"]
    name = message.name or "tool"
    tool_status = getattr(message, "status", None)
    if name == "call_mail_reader":
        summary, emails, title = _parse_mail_reader_payload(_message_text(message.content))
        blocks.append(_tool_action_block(_label_for_tool(name), "complete"))
        if summary:
            blocks.append(_summary_block("Inbox Summary", summary))
        if emails:
            blocks.append(_email_list_block(title or "Email Results", emails))
        return
    if name == "call_web_search":
        summary = _parse_research_payload(_message_text(message.content))
        blocks.append(_tool_action_block(_label_for_tool(name), "complete"))
        if summary:
            blocks.append(_research_report_block("Research Notes", summary))
        return
    if name == "call_mailing_agent":
        blocks.append(_tool_action_block(_label_for_tool(name), "complete"))
        turn["draft_slots"] += 1
        return
    if name == "send_email":
        if tool_status == "error":
            turn["status"] = "error"
            blocks.append(_status_block("Email send failed", "error", _message_text(message.content)))
        else:
            blocks.append(_tool_action_block(_label_for_tool(name), "complete"))
            blocks.append(_status_block("Email sent", "success", _message_text(message.content)))
        return

    blocks.append(_tool_action_block(_label_for_tool(name), "complete", _message_text(message.content)))


def _finalize_turn(turn: dict[str, Any], drafts: list[EmailDraft], draft_index: int) -> tuple[ChatMessageResponse | None, int]:
    if not turn["content_blocks"] and not drafts:
        return None, draft_index

    blocks = list(turn["content_blocks"])
    slots = max(turn.get("draft_slots", 0), 0)
    while draft_index < len(drafts) and slots > 0:
        blocks.append(_draft_block(drafts[draft_index]))
        if drafts[draft_index].status == "pending_approval":
            turn["status"] = "waiting_approval"
            blocks.insert(0, _status_block("Waiting for approval", "pending"))
        elif drafts[draft_index].status == "rejected":
            blocks.insert(0, _status_block("Rewrite requested", "warning"))
        elif drafts[draft_index].status == "sent":
            turn["status"] = "complete"
        elif drafts[draft_index].status == "send_failed":
            turn["status"] = "error"
        draft_index += 1
        slots -= 1
        if slots <= 0:
            break

    content = _content_from_blocks(blocks)
    return (
        ChatMessageResponse(
            id=turn["id"],
            role="assistant",
            content=content,
            content_blocks=blocks,
            status=turn["status"],
            turn_id=turn["turn_id"],
            created_at=turn["created_at"],
        ),
        draft_index,
    )


def _serialize_history(messages: list[BaseMessage], drafts: list[EmailDraft]) -> list[ChatMessageResponse]:
    serialized: list[ChatMessageResponse] = []
    current_turn: dict[str, Any] | None = None
    draft_index = 0
    assistant_counter = 0

    for index, message in enumerate(messages):
        if isinstance(message, HumanMessage):
            if current_turn is not None:
                item, draft_index = _finalize_turn(current_turn, drafts, draft_index)
                if item is not None:
                    serialized.append(item)
                current_turn = None
            serialized.append(_build_user_message(message, index))
            continue

        if current_turn is None:
            current_turn = _start_assistant_turn(assistant_counter)
            assistant_counter += 1

        if isinstance(message, AIMessage):
            content = _message_text(message.content).strip()
            if content:
                _append_markdown(current_turn["content_blocks"], content)
        elif isinstance(message, ToolMessage):
            _apply_tool_message_to_turn(current_turn, message)

    if current_turn is not None:
        item, draft_index = _finalize_turn(current_turn, drafts, draft_index)
        if item is not None:
            serialized.append(item)

    while draft_index < len(drafts):
        for item in reversed(serialized):
            if item.role == "assistant":
                blocks = list(item.content_blocks or [])
                blocks.append(_draft_block(drafts[draft_index]))
                if drafts[draft_index].status == "pending_approval":
                    item.status = "waiting_approval"
                item.content_blocks = blocks
                draft_index += 1
                break
        else:
            break

    return serialized


async def _get_owned_conversation(db: AsyncSession, conversation_id: str, user_id: uuid.UUID) -> Conversation:
    conversation = await db.get(Conversation, uuid.UUID(conversation_id))
    if conversation is None or conversation.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


async def _get_conversation_history(request: Request, db: AsyncSession, conversation_id: str) -> list[ChatMessageResponse]:
    checkpoint_tuple = await request.app.state.checkpointer.aget_tuple({"configurable": {"thread_id": conversation_id}})
    checkpoint_messages = checkpoint_tuple.checkpoint.get("channel_values", {}).get("messages", []) if checkpoint_tuple else []

    draft_rows = await db.scalars(
        select(EmailDraft)
        .where(EmailDraft.conversation_id == uuid.UUID(conversation_id))
        .order_by(EmailDraft.created_at)
    )
    drafts = draft_rows.all()
    return _serialize_history(checkpoint_messages, drafts)


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
    return await _get_conversation_history(request, db, conversation_id)


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
        turn_id = str(uuid.uuid4())
        yield _sse({"type": "turn_started", "turn_id": turn_id})
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
                        yield _sse({"type": "token", "content": text, "turn_id": turn_id})
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
                                        "conversation_id": payload.conversation_id,
                                        "turn_id": turn_id,
                                    }
                                )
            yield _sse({"type": "turn_completed", "turn_id": turn_id})
            yield _sse({"type": "done", "turn_id": turn_id})
        except Exception as exc:
            yield _sse({"type": "error", "content": str(exc), "turn_id": turn_id})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
