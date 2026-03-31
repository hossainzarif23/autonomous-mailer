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

