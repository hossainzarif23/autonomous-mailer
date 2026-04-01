from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_draft import EmailDraft
from app.services.notification_service import NotificationService


def _send_email_requests(interrupt_value: dict[str, Any]) -> list[dict[str, Any]]:
    action_requests = interrupt_value.get("action_requests")
    if not isinstance(action_requests, list):
        return []

    requests: list[dict[str, Any]] = []
    for action_request in action_requests:
        if not isinstance(action_request, dict):
            continue
        if action_request.get("name") != "send_email":
            continue

        args = action_request.get("args")
        if not isinstance(args, dict):
            continue

        requests.append(
            {
                "args": args,
                "description": str(action_request.get("description") or "").strip() or None,
            }
        )
    return requests


def is_hitl_interrupt(interrupt_value: Any) -> bool:
    return bool(isinstance(interrupt_value, dict) and _send_email_requests(interrupt_value))


def serialize_draft_for_frontend(draft: EmailDraft, *, description: str | None = None) -> dict[str, Any]:
    return {
        "id": str(draft.id),
        "conversation_id": str(draft.conversation_id) if draft.conversation_id else None,
        "to": draft.edited_to or draft.to_address,
        "subject": draft.edited_subject or draft.subject,
        "body": draft.edited_body or draft.body,
        "draft_type": draft.draft_type,
        "status": draft.status,
        "description": description,
    }


async def persist_hitl_interrupts(
    db: AsyncSession,
    *,
    user_id: str,
    conversation_id: str,
    interrupt_value: dict[str, Any],
    notification_service: NotificationService,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for request in _send_email_requests(interrupt_value):
        args = request["args"]
        description = request["description"]
        draft = EmailDraft(
            id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            conversation_id=uuid.UUID(conversation_id),
            draft_type=str(args.get("draft_type") or "fresh"),
            to_address=str(args.get("to") or "").strip(),
            subject=str(args.get("subject") or "").strip(),
            body=str(args.get("body") or "").strip(),
            in_reply_to=str(args.get("in_reply_to")) if args.get("in_reply_to") else None,
            thread_id=str(args.get("thread_id")) if args.get("thread_id") else None,
            status="pending_approval",
        )
        db.add(draft)
        await db.commit()
        await db.refresh(draft)

        draft_payload = serialize_draft_for_frontend(draft, description=description)
        event = {
            "type": "approval_required",
            "draft_id": str(draft.id),
            "conversation_id": conversation_id,
            "draft": draft_payload,
            "description": description,
        }
        await notification_service.create_notification(
            db,
            user_id,
            type="approval_required",
            title="Approval Required",
            body="A draft is waiting for your approval.",
            metadata={
                "draft_id": str(draft.id),
                "conversation_id": conversation_id,
                "draft": draft_payload,
                "description": description,
            },
        )
        await notification_service.broadcast(user_id, event)
        events.append(event)

    return events
