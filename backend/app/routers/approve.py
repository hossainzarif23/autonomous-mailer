from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from langgraph.types import Command
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import AgentContext
from app.agents.coordinator import get_coordinator_agent
from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.email_draft import EmailDraft
from app.models.user import User
from app.schemas.approval import ApprovalRequest, ApprovalResponse
from app.services.auth_service import get_valid_access_token
from app.services.gmail_service import GmailService
from app.services.hitl_service import is_hitl_interrupt, persist_hitl_interrupts
from app.services.notification_service import notification_service

router = APIRouter()


def _serialize_draft(draft: EmailDraft) -> dict:
    return {
        "id": str(draft.id),
        "conversation_id": str(draft.conversation_id) if draft.conversation_id else None,
        "draft_type": draft.draft_type,
        "to": draft.edited_to or draft.to_address,
        "subject": draft.edited_subject or draft.subject,
        "body": draft.edited_body or draft.body,
        "status": draft.status,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
    }


def _build_decision(draft: EmailDraft, payload: ApprovalRequest) -> dict:
    if payload.action == "reject":
        return {
            "type": "reject",
            "message": payload.feedback or "Please revise the draft based on my feedback.",
        }

    edited_to = payload.edited_to or draft.to_address
    edited_subject = payload.edited_subject or draft.subject
    edited_body = payload.edited_body or draft.body
    edited = (
        edited_to != draft.to_address
        or edited_subject != draft.subject
        or edited_body != draft.body
    )
    if payload.action == "edit" or edited:
        return {
            "type": "edit",
            "edited_action": {
                "name": "send_email",
                "args": {
                    "to": edited_to,
                    "subject": edited_subject,
                    "body": edited_body,
                    "draft_type": draft.draft_type,
                    "in_reply_to": draft.in_reply_to,
                    "thread_id": draft.thread_id,
                },
            },
        }
    return {"type": "approve"}


def _current_draft_payload(draft: EmailDraft, payload: ApprovalRequest) -> dict:
    return {
        "to": payload.edited_to or draft.to_address,
        "subject": payload.edited_subject or draft.subject,
        "body": payload.edited_body or draft.body,
        "draft_type": draft.draft_type,
        "in_reply_to": draft.in_reply_to,
        "thread_id": draft.thread_id,
    }


def _feedback_requires_research(feedback: str | None) -> bool:
    if not feedback:
        return False
    lowered = feedback.lower()
    cues = (
        "latest",
        "recent",
        "current",
        "up-to-date",
        "updated data",
        "new data",
        "fact-check",
        "facts",
        "statistics",
        "stat",
        "source",
        "sources",
        "trend",
        "market",
        "research",
    )
    return any(cue in lowered for cue in cues)


@router.get("/pending")
async def list_pending_approvals(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    drafts = await db.scalars(
        select(EmailDraft)
        .where(
            EmailDraft.user_id == current_user.id,
            EmailDraft.status == "pending_approval",
        )
        .order_by(desc(EmailDraft.created_at))
    )
    return [_serialize_draft(draft) for draft in drafts.all()]


@router.post("/{draft_id}", response_model=ApprovalResponse)
async def approve_draft(
    draft_id: str,
    payload: ApprovalRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    draft = await db.get(EmailDraft, UUID(draft_id))
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    if draft.status != "pending_approval":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Draft is not pending approval")
    if draft.conversation_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Draft is missing a conversation")

    if payload.action in {"edit", "approve"}:
        draft.edited_to = payload.edited_to if payload.edited_to and payload.edited_to != draft.to_address else None
        draft.edited_subject = (
            payload.edited_subject
            if payload.edited_subject and payload.edited_subject != draft.subject
            else None
        )
        draft.edited_body = payload.edited_body if payload.edited_body and payload.edited_body != draft.body else None
        draft.updated_at = datetime.now(UTC)
        await db.commit()
    elif payload.action == "reject":
        draft.status = "rejected"
        draft.updated_at = datetime.now(UTC)
        await db.commit()

    access_token = await get_valid_access_token(str(current_user.id), db)
    context = AgentContext(
        user_id=str(current_user.id),
        conversation_id=str(draft.conversation_id),
        gmail_service=GmailService(access_token),
        db_session=db,
        notification_service=notification_service,
    )

    coordinator = get_coordinator_agent(request.app.state.checkpointer)
    async for part in coordinator.astream(
        Command(
            resume={"decisions": [_build_decision(draft, payload)]},
            update={
                "current_draft": _current_draft_payload(draft, payload),
                "draft_feedback": payload.feedback if payload.action == "reject" else None,
                "needs_research_refresh": (
                    draft.draft_type == "fresh"
                    and payload.action == "reject"
                    and _feedback_requires_research(payload.feedback)
                ),
            },
        ),
        config={"configurable": {"thread_id": str(draft.conversation_id)}},
        context=context,
        stream_mode=["updates"],
        version="v2",
    ):
        if part["type"] != "updates":
            continue
        interrupts = part["data"].get("__interrupt__", ())
        for interrupt in interrupts:
            interrupt_value = getattr(interrupt, "value", interrupt)
            if is_hitl_interrupt(interrupt_value):
                await persist_hitl_interrupts(
                    db,
                    user_id=str(current_user.id),
                    conversation_id=str(draft.conversation_id),
                    interrupt_value=interrupt_value,
                    notification_service=notification_service,
                )

    await db.refresh(draft)
    return ApprovalResponse(
        success=True,
        status=draft.status,
        gmail_message_id=draft.gmail_sent_id,
    )
