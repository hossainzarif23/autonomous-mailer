from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.gmail_service import GmailService
from app.services.notification_service import NotificationService


@dataclass
class AgentContext:
    user_id: str
    gmail_service: GmailService
    db_session: AsyncSession
    notification_service: NotificationService
