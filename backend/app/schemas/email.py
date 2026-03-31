from __future__ import annotations

from pydantic import BaseModel


class EmailSummary(BaseModel):
    message_id: str
    thread_id: str
    from_name: str
    from_email: str
    subject: str
    snippet: str
    date: str


class EmailDetail(EmailSummary):
    to: str
    cc: str
    body: str
    label_ids: list[str]
    gmail_message_header: str
    references: str
    in_reply_to: str
