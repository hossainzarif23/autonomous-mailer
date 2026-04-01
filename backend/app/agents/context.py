from __future__ import annotations

from uuid import UUID
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.gmail_service import GmailService
from app.services.notification_service import NotificationService


@dataclass
class AgentContext:
    user_id: str
    conversation_id: str
    gmail_service: GmailService
    db_session: AsyncSession
    notification_service: NotificationService

    @property
    def user_uuid(self) -> UUID:
        return UUID(self.user_id)

    @property
    def conversation_uuid(self) -> UUID:
        return UUID(self.conversation_id)
