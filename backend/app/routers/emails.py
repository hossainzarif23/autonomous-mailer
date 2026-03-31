from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.schemas.email import EmailDetail, EmailSummary
from app.services.auth_service import get_valid_access_token
from app.services.gmail_service import GmailService

router = APIRouter()


async def _get_gmail_service(current_user: User, db: AsyncSession) -> GmailService:
    access_token = await get_valid_access_token(str(current_user.id), db)
    return GmailService(access_token)


def _to_summary(message: dict) -> EmailSummary:
    return EmailSummary(
        message_id=message["message_id"],
        thread_id=message["thread_id"],
        from_name=message["from_name"],
        from_email=message["from_email"],
        subject=message["subject"],
        snippet=message["snippet"],
        date=message["date"],
    )


def _to_detail(message: dict) -> EmailDetail:
    return EmailDetail(
        message_id=message["message_id"],
        thread_id=message["thread_id"],
        from_name=message["from_name"],
        from_email=message["from_email"],
        subject=message["subject"],
        snippet=message["snippet"],
        date=message["date"],
        to=message["to"],
        cc=message["cc"],
        body=message["body"],
        label_ids=message["label_ids"],
        gmail_message_header=message["gmail_message_header"],
        references=message["references"],
        in_reply_to=message["in_reply_to"],
    )


@router.get("/recent", response_model=list[EmailSummary])
async def get_recent_emails(
    count: int = Query(default=5, ge=1, le=20),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    gmail = await _get_gmail_service(current_user, db)
    emails = await gmail.list_messages(max_results=count)
    return [_to_summary(email) for email in emails]


@router.get("/search", response_model=list[EmailSummary])
async def search_emails(
    q: str | None = Query(default=None),
    sender: str | None = Query(default=None),
    topic: str | None = Query(default=None),
    count: int = Query(default=10, ge=1, le=20),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    gmail = await _get_gmail_service(current_user, db)
    query = gmail._build_query(sender=sender, topic=topic, query=q)
    emails = await gmail.list_messages(query=query, max_results=count)
    return [_to_summary(email) for email in emails]


@router.get("/{message_id}", response_model=EmailDetail)
async def get_email(
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    gmail = await _get_gmail_service(current_user, db)
    message = await gmail.get_message(message_id)
    return _to_detail(message)
