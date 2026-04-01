from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

from app.agents.tools.draft_tools import compose_and_request_approval
from app.agents.tools.gmail_tools import get_recent_emails
from app.services.notification_service import NotificationService


class AgentToolTests(IsolatedAsyncioTestCase):
    async def test_get_recent_emails_formats_messages(self):
        gmail_service = SimpleNamespace(
            list_messages=AsyncMock(
                return_value=[
                    {
                        "subject": "Quarterly Update",
                        "from_name": "Finance Bot",
                        "from_email": "finance@example.com",
                        "date": "Mon, 31 Mar 2026 10:00:00 +0000",
                        "message_id": "msg-1",
                        "thread_id": "thread-1",
                        "snippet": "Numbers attached",
                    }
                ]
            )
        )
        runtime = SimpleNamespace(context=SimpleNamespace(gmail_service=gmail_service))

        result = await get_recent_emails.coroutine(1, runtime=runtime)

        self.assertIn("Quarterly Update", result)
        self.assertIn("Finance Bot <finance@example.com>", result)

    async def test_compose_and_request_approval_persists_draft_before_interrupt_context_is_required(self):
        db_session = SimpleNamespace(add=MagicMock(), commit=AsyncMock(), refresh=AsyncMock())
        runtime = SimpleNamespace(
            context=SimpleNamespace(
                user_id=str(uuid.uuid4()),
                conversation_id=str(uuid.uuid4()),
                db_session=db_session,
                gmail_service=SimpleNamespace(send_email=AsyncMock()),
                notification_service=NotificationService(),
            )
        )

        with self.assertRaisesRegex(RuntimeError, "outside of a runnable context"):
            await compose_and_request_approval.coroutine(
                to="ceo@example.com",
                subject="Hello",
                body="Test body",
                draft_type="fresh",
                in_reply_to=None,
                thread_id=None,
                runtime=runtime,
            )

        db_session.commit.assert_awaited()
        db_session.refresh.assert_awaited()
