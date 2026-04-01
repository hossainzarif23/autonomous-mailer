from __future__ import annotations

from sqlalchemy import desc, select
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
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


async def _get_latest_pending_draft(runtime: ToolRuntime[AgentContext]) -> EmailDraft | None:
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
    db = runtime.context.db_session
    draft = await _get_latest_pending_draft(runtime)
    tool_call_id = runtime.tool_call_id or "send_email"
    in_reply_to = _normalize_optional_identifier(in_reply_to)
    thread_id = _normalize_optional_identifier(thread_id)

    try:
        gmail_id = await runtime.context.gmail_service.send_email(
            to=to,
            subject=subject,
            body=body,
            in_reply_to=in_reply_to,
            thread_id=thread_id,
        )

        if draft is not None:
            draft.status = "sent"
            draft.edited_to = to if to != draft.to_address else None
            draft.edited_subject = subject if subject != draft.subject else None
            draft.edited_body = body if body != draft.body else None
            draft.gmail_sent_id = gmail_id
            await db.commit()

        event = {
            "type": "email_sent",
            "title": "Email Sent",
            "body": f"Your email to {to} has been sent.",
            "draft_id": str(draft.id) if draft is not None else None,
            "gmail_message_id": gmail_id,
        }
        await runtime.context.notification_service.create_notification(
            db,
            runtime.context.user_id,
            type="email_sent",
            title="Email Sent",
            body=f"Your email to {to} has been sent.",
            metadata={
                "draft_id": str(draft.id) if draft is not None else None,
                "gmail_message_id": gmail_id,
                "draft_type": draft_type,
            },
        )
        await runtime.context.notification_service.broadcast(runtime.context.user_id, event)
        return Command(
            update={
                "current_draft": None,
                "draft_feedback": None,
                "needs_research_refresh": False,
                "messages": [
                    ToolMessage(
                        content=f"Email successfully sent to {to}. Gmail message ID: {gmail_id}",
                        name="send_email",
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )
    except Exception as exc:
        if draft is not None:
            draft.status = "send_failed"
            await db.commit()

        await runtime.context.notification_service.create_notification(
            db,
            runtime.context.user_id,
            type="error",
            title="Email Send Failed",
            body=str(exc),
            metadata={"draft_id": str(draft.id) if draft is not None else None},
        )
        await runtime.context.notification_service.broadcast(
            runtime.context.user_id,
            {
                "type": "error",
                "title": "Email Send Failed",
                "content": str(exc),
                "draft_id": str(draft.id) if draft is not None else None,
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
