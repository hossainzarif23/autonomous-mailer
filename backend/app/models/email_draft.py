from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class EmailDraft(Base):
    __tablename__ = "email_drafts"
    __table_args__ = (
        CheckConstraint("draft_type IN ('reply', 'fresh')", name="ck_email_drafts_draft_type"),
        CheckConstraint(
            "status IN ('pending_approval', 'approved', 'rejected', 'sent', 'send_failed')",
            name="ck_email_drafts_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    draft_type: Mapped[str] = mapped_column(String(20), nullable=False)
    to_address: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    in_reply_to: Mapped[str | None] = mapped_column(String(500), nullable=True)
    thread_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending_approval", nullable=False)
    edited_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    edited_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    edited_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    gmail_sent_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user = relationship("User", back_populates="email_drafts")
    conversation = relationship("Conversation", back_populates="email_drafts")

