from __future__ import annotations

import uuid

from langchain.tools import ToolRuntime, tool
from langgraph.types import interrupt

from app.agents.context import AgentContext
from app.models.email_draft import EmailDraft


@tool
async def compose_and_request_approval(
    to: str,
    subject: str,
    body: str,
    draft_type: str,
    in_reply_to: str | None,
    thread_id: str | None,
    conversation_id: str,
    runtime: ToolRuntime[AgentContext],
) -> str:
    """Persist a draft, pause for approval, then send the email if approved."""
    db = runtime.context.db_session
    user_id = uuid.UUID(runtime.context.user_id)

    draft = EmailDraft(
        id=uuid.uuid4(),
        user_id=user_id,
        conversation_id=uuid.UUID(conversation_id),
        draft_type=draft_type,
        to_address=to,
        subject=subject,
        body=body,
        in_reply_to=in_reply_to,
        thread_id=thread_id,
        status="pending_approval",
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)

    approval = interrupt(
        {
            "type": "approval_required",
            "draft_id": str(draft.id),
            "draft": {
                "to": to,
                "subject": subject,
                "body": body,
                "draft_type": draft_type,
            },
        }
    )

    if not approval.get("approved"):
        draft.status = "rejected"
        await db.commit()
        return "The email was not sent because the user rejected it."

    final_to = approval.get("edited_to") or to
    final_subject = approval.get("edited_subject") or subject
    final_body = approval.get("edited_body") or body

    gmail = runtime.context.gmail_service
    try:
        gmail_id = await gmail.send_email(
            to=final_to,
            subject=final_subject,
            body=final_body,
            in_reply_to=in_reply_to,
            thread_id=thread_id,
        )
        draft.status = "sent"
        draft.edited_to = approval.get("edited_to")
        draft.edited_subject = approval.get("edited_subject")
        draft.edited_body = approval.get("edited_body")
        draft.gmail_sent_id = gmail_id
        await db.commit()

        await runtime.context.notification_service.broadcast(
            runtime.context.user_id,
            {
                "type": "email_sent",
                "title": "Email Sent",
                "body": f"Your email to {final_to} has been sent.",
                "draft_id": str(draft.id),
            },
        )
        return f"Email successfully sent to {final_to}. Gmail message ID: {gmail_id}"
    except Exception as exc:
        draft.status = "send_failed"
        await db.commit()
        return f"Failed to send email: {str(exc)}"
