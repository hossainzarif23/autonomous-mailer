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


def _approval_blocked_event(*, draft_id: str, conversation_id: str, turn_id: str) -> dict[str, Any]:
    return {
        "type": "approval_blocked",
        "draft_id": draft_id,
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "content": "Review the pending draft before sending another message in this conversation.",
    }


def _blocked_approval_events(*, draft_id: str, conversation_id: str, turn_id: str) -> list[dict[str, Any]]:
    return [
        _approval_blocked_event(draft_id=draft_id, conversation_id=conversation_id, turn_id=turn_id),
        {"type": "done", "turn_id": turn_id},
    ]


async def _pending_approval_blocked_stream_events(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: str,
    turn_id: str,
) -> list[str] | None:
    pending_draft = await _get_pending_approval_draft(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    if pending_draft is None:
        return None
    return [
        _sse(event)
        for event in _blocked_approval_events(
            draft_id=str(pending_draft.id),
            conversation_id=conversation_id,
            turn_id=turn_id,
        )
    ]


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
    parsed_get_full_email: str | None = None
    # The sub-agent may call `get_emails` multiple times while iterating
    # toward the answer (e.g. retrying with a different filter, or fetching
    # individual messages with `get_full_email`). The LAST successful
    # `get_emails` output reflects the agent's final answer; intermediate
    # fetches and `get_full_email` calls don't change which list of emails
    # the user sees. Use the last one, not the first.
    for output in payload.get("tool_outputs", []):
        if not isinstance(output, dict):
            continue
        name = str(output.get("name") or "")
        raw_output = str(output.get("content") or "")
        if name == "get_full_email" and raw_output.strip():
            parsed_get_full_email = raw_output.strip()
            continue
        parsed = _parse_email_entries(raw_output)
        if parsed:
            emails = parsed
            if name == "get_email_thread":
                title = "Thread Messages"
            else:
                title = "Email Results"

    if emails:
        if title is None:
            title = "Email Results"
    elif parsed_get_full_email:
        title = "Email Detail"
        summary = summary or parsed_get_full_email
    else:
        summary = summary or "No matching emails were found."
        title = None

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


def _looks_like_json_payload(content: str) -> bool:
    stripped = content.strip()
    if not stripped:
        return False
    if not (
        (stripped.startswith("{") and stripped.endswith("}"))
        or (stripped.startswith("[") and stripped.endswith("]"))
    ):
        return False
    try:
        json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return True


def _safe_token_content(chunk: Any) -> str | None:
    if getattr(chunk, "tool_calls", None):
        return None
    content = _message_text(getattr(chunk, "content", "")).strip()
    if not content:
        return None
    if _looks_like_json_payload(content):
        return None
    return content


def _tool_call_details(chunk: Any) -> list[tuple[str, str | None]]:
    tool_calls: list[tuple[str, str | None]] = []
    for tool_call in getattr(chunk, "tool_calls", None) or []:
        if isinstance(tool_call, dict):
            name = tool_call.get("name")
            tool_call_id = tool_call.get("id")
        else:
            name = getattr(tool_call, "name", None)
            tool_call_id = getattr(tool_call, "id", None)
        if name:
            tool_calls.append((str(name), str(tool_call_id) if tool_call_id else None))
    return tool_calls


def _tool_call_detail(tool_call: Any, *, turn_id: str, occurrence_index: int) -> tuple[str, str]:
    if isinstance(tool_call, dict):
        name = tool_call.get("name")
        tool_call_id = tool_call.get("id")
    else:
        name = getattr(tool_call, "name", None)
        tool_call_id = getattr(tool_call, "id", None)

    tool_name = str(name or "tool")
    if tool_call_id:
        return tool_name, str(tool_call_id)
    return tool_name, f"generated:{turn_id}:{occurrence_index}"


def _tool_call_names(chunk: Any) -> list[str]:
    return [name for name, _tool_call_id in _tool_call_details(chunk)]


def _action_started_event(tool_name: str, *, turn_id: str, tool_call_id: str | None = None) -> dict[str, Any]:
    event = {
        "type": "action_started",
        "tool": tool_name,
        "label": _label_for_tool(tool_name),
        "turn_id": turn_id,
    }
    if tool_call_id is not None:
        event["tool_call_id"] = tool_call_id
    return event


def _action_completed_event(tool_name: str, *, turn_id: str, tool_call_id: str | None = None) -> dict[str, Any]:
    event = {
        "type": "action_completed",
        "tool": tool_name,
        "label": _label_for_tool(tool_name),
        "turn_id": turn_id,
    }
    if tool_call_id is not None:
        event["tool_call_id"] = tool_call_id
    return event


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


async def _get_pending_approval_draft(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: str,
) -> EmailDraft | None:
    result = await db.scalars(
        select(EmailDraft)
        .where(
            EmailDraft.user_id == user_id,
            EmailDraft.conversation_id == uuid.UUID(conversation_id),
            EmailDraft.status == "pending_approval",
        )
        .order_by(desc(EmailDraft.created_at))
        .limit(1)
    )
    return result.first()


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

    async def event_stream():
        turn_id = str(uuid.uuid4())
        seen_started_tool_call_ids: set[str] = set()
        seen_completed_tool_call_ids: set[str] = set()
        pending_idless_tool_call_ids_by_name: dict[str, list[str]] = {}
        generated_tool_call_index = 0
        yield _sse({"type": "turn_started", "turn_id": turn_id})
        try:
            blocked_events = await _pending_approval_blocked_stream_events(
                db,
                user_id=current_user.id,
                conversation_id=payload.conversation_id,
                turn_id=turn_id,
            )
            if blocked_events is not None:
                for event in blocked_events:
                    yield event
                return
            if conversation.title is None:
                conversation.title = payload.message.strip()[:80] or "New conversation"
            conversation.updated_at = datetime.now(UTC)
            await db.commit()
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
                    chunk, metadata = part["data"]
                    # Only stream prose produced by the coordinator itself.
                    # Sub-agent LLM tokens (web_search_agent, mail_reader_agent,
                    # mailing_agent) come through this same stream but their prose
                    # is destined for structured ToolMessage content — not raw
                    # markdown. Suppressing them here prevents sub-agent prose
                    # from leaking into the user's chat as duplicated content.
                    node_name = metadata.get("langgraph_node") if isinstance(metadata, dict) else None
                    if node_name and node_name != "agent":
                        continue
                    tool_calls = getattr(chunk, "tool_calls", None) or []
                    if tool_calls:
                        for tool_call in tool_calls:
                            if isinstance(tool_call, dict):
                                raw_tool_call_id = tool_call.get("id")
                            else:
                                raw_tool_call_id = getattr(tool_call, "id", None)
                            tool_name, tool_call_id = _tool_call_detail(
                                tool_call,
                                turn_id=turn_id,
                                occurrence_index=generated_tool_call_index + 1,
                            )
                            if not raw_tool_call_id:
                                generated_tool_call_index += 1
                                pending_idless_tool_call_ids_by_name.setdefault(tool_name, []).append(tool_call_id)
                            else:
                                if tool_call_id in seen_started_tool_call_ids:
                                    continue
                                seen_started_tool_call_ids.add(tool_call_id)
                            yield _sse(
                                _action_started_event(
                                    tool_name,
                                    turn_id=turn_id,
                                    tool_call_id=tool_call_id,
                                )
                            )
                        continue
                    text = _safe_token_content(chunk)
                    if text:
                        yield _sse({"type": "token", "content": text, "turn_id": turn_id})
                elif part["type"] == "updates":
                    updates = part["data"]
                    for node_update in updates.values():
                        if not isinstance(node_update, dict):
                            continue
                        for message in node_update.get("messages", []):
                            if isinstance(message, ToolMessage) and message.name:
                                tool_call_id = getattr(message, "tool_call_id", None)
                                if not tool_call_id:
                                    pending_ids = pending_idless_tool_call_ids_by_name.get(message.name)
                                    if pending_ids:
                                        tool_call_id = pending_ids.pop(0)
                                    else:
                                        generated_tool_call_index += 1
                                        tool_call_id = f"generated:{turn_id}:{generated_tool_call_index}"
                                else:
                                    if tool_call_id in seen_completed_tool_call_ids:
                                        continue
                                    seen_completed_tool_call_ids.add(tool_call_id)
                                yield _sse(
                                    _action_completed_event(
                                        message.name,
                                        turn_id=turn_id,
                                        tool_call_id=tool_call_id,
                                    )
                                )
                                if message.name == "call_web_search":
                                    # Surface the research content as a structured
                                    # block during the stream so the frontend can
                                    # render it via MarkdownResponse without waiting
                                    # for the history reload. The frontend dedupes
                                    # against any duplicate research_report block
                                    # produced on history rehydration.
                                    summary = _parse_research_payload(_message_text(message.content))
                                    if summary:
                                        yield _sse(
                                            {
                                                "type": "research_report",
                                                "turn_id": turn_id,
                                                "tool_call_id": tool_call_id,
                                                "title": "Research Notes",
                                                "content": summary,
                                            }
                                        )
                                elif message.name == "call_mailing_agent":
                                    # The coordinator wraps the draft JSON into the
                                    # tool message; pass it to the frontend as a
                                    # typed artifact so it can render the
                                    # draft_email block in real time.
                                    try:
                                        draft_payload = json.loads(_message_text(message.content))
                                        if isinstance(draft_payload, dict) and "to" in draft_payload:
                                            yield _sse(
                                                {
                                                    "type": "draft_artifact",
                                                    "turn_id": turn_id,
                                                    "tool_call_id": tool_call_id,
                                                    "draft": draft_payload,
                                                }
                                            )
                                    except (json.JSONDecodeError, ValueError):
                                        pass
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
                                # The full approval_required event (with draft body)
                                # is yielded on the request-scoped stream so the active
                                # tab opens the modal even if the notification EventSource
                                # is dead or reconnecting. The notification broadcast
                                # already happened inside persist_hitl_interrupts for
                                # other tabs / devices.
                                yield _sse(
                                    {
                                        **event,
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
