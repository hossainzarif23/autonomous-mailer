from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, select
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command

from app.agents.context import AgentContext
from app.models.email_draft import EmailDraft


def _normalize_optional_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or normalized.lower() in {"null", "none", "nil"}:
        return None
    return normalized


async def _pending_draft(runtime: ToolRuntime[AgentContext]) -> EmailDraft | None:
    """Return the most recent pending_approval row for this user + conversation."""
    db = runtime.context.db_session
    result = await db.scalars(
        select(EmailDraft)
        .where(
            EmailDraft.user_id == runtime.context.user_uuid,
            EmailDraft.conversation_id == runtime.context.conversation_uuid,
            EmailDraft.status == "pending_approval",
        )
        .order_by(desc(EmailDraft.created_at))
        .limit(1)
    )
    return result.first()


async def _mark_draft_sent(
    db,
    draft: EmailDraft,
    *,
    to: str,
    subject: str,
    body: str,
    gmail_id: str,
) -> None:
    """Update the draft row to sent and record the user edits that diverged from the LLM draft."""
    draft.status = "sent"
    draft.gmail_sent_id = gmail_id
    draft.edited_to = to if to != draft.to_address else None
    draft.edited_subject = subject if subject != draft.subject else None
    draft.edited_body = body if body != draft.body else None
    draft.updated_at = datetime.now(UTC)
    await db.commit()


async def _mark_draft_send_failed(db, draft: EmailDraft | None) -> None:
    if draft is None:
        return
    draft.status = "send_failed"
    draft.updated_at = datetime.now(UTC)
    await db.commit()


@tool
async def send_email(
    to: str,
    subject: str,
    body: str,
    draft_type: str,
    in_reply_to: str | None,
    thread_id: str | None,
    runtime: ToolRuntime[AgentContext],
) -> str:
    """Send the final email after human approval."""
    tool_call_id = runtime.tool_call_id or "send_email"
    in_reply_to = _normalize_optional_identifier(in_reply_to)
    thread_id = _normalize_optional_identifier(thread_id)
    db = runtime.context.db_session
    draft = await _pending_draft(runtime)
    draft_id = str(draft.id) if draft is not None else None

    try:
        gmail_id = await runtime.context.gmail_service.send_email(
            to=to,
            subject=subject,
            body=body,
            in_reply_to=in_reply_to,
            thread_id=thread_id,
        )
    except Exception as exc:
        await _mark_draft_send_failed(db, draft)
        await runtime.context.notification_service.create_notification(
            db,
            runtime.context.user_id,
            type="error",
            title="Email Send Failed",
            body=str(exc),
            metadata={
                "draft_id": draft_id,
                "conversation_id": runtime.context.conversation_id,
            },
        )
        await runtime.context.notification_service.broadcast(
            runtime.context.user_id,
            {
                "type": "error",
                "title": "Email Send Failed",
                "content": str(exc),
                "draft_id": draft_id,
                "conversation_id": runtime.context.conversation_id,
            },
        )
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"Failed to send email: {str(exc)}",
                        name="send_email",
                        tool_call_id=tool_call_id,
                        status="error",
                    )
                ]
            }
        )

    if draft is not None:
        await _mark_draft_sent(
            db,
            draft,
            to=to,
            subject=subject,
            body=body,
            gmail_id=gmail_id,
        )

    event = {
        "type": "email_sent",
        "title": "Email Sent",
        "body": f"Your email to {to} has been sent.",
        "draft_id": draft_id,
        "conversation_id": runtime.context.conversation_id,
        "gmail_message_id": gmail_id,
    }
    await runtime.context.notification_service.create_notification(
        db,
        runtime.context.user_id,
        type="email_sent",
        title="Email Sent",
        body=f"Your email to {to} has been sent.",
        metadata={
            "draft_id": draft_id,
            "conversation_id": runtime.context.conversation_id,
            "gmail_message_id": gmail_id,
            "draft_type": draft_type,
        },
    )
    await runtime.context.notification_service.broadcast(runtime.context.user_id, event)
    return Command(
        update={
            "current_draft": None,
            "draft_feedback": None,
            "messages": [
                ToolMessage(
                    content=f"Email successfully sent to {to}. Gmail message ID: {gmail_id}",
                    name="send_email",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )

