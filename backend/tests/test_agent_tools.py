from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents.context import AgentContext
from app.agents.tools.draft_tools import send_email
from app.agents.tools.gmail_tools import get_recent_emails


@pytest.mark.asyncio
async def test_get_recent_emails_formats_messages():
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

    assert "Quarterly Update" in result
    assert "Finance Bot <finance@example.com>" in result


@pytest.mark.asyncio
async def test_send_email_uses_tool_arguments_and_updates_draft_row():
    """send_email sends with the tool's own arguments (not the DB row) and,
    on success, updates the pending draft row to status=sent with the gmail id."""
    pending_draft_id = uuid.uuid4()
    user_id = uuid.uuid4()
    conversation_id = uuid.uuid4()

    pending_draft = SimpleNamespace(
        id=pending_draft_id,
        to_address="ceo@example.com",
        subject="Original subject",
        body="Original body",
        status="pending_approval",
    )

    class _ScalarsResult:
        def first(self_inner):
            return pending_draft

    class _Db:
        def __init__(self):
            self.scalars = AsyncMock(return_value=_ScalarsResult())
            self.commit = AsyncMock()

    gmail_service = SimpleNamespace(
        send_email=AsyncMock(return_value="gmail-sent-id-42")
    )
    notification_service = SimpleNamespace(
        create_notification=AsyncMock(),
        broadcast=AsyncMock(),
    )
    db = _Db()
    context = AgentContext(
        user_id=str(user_id),
        conversation_id=str(conversation_id),
        gmail_service=gmail_service,
        db_session=db,
        notification_service=notification_service,
    )
    runtime = SimpleNamespace(context=context, tool_call_id="call-send-1")

    result = await send_email.coroutine(
        to="ceo@example.com",
        subject="Edited subject",
        body="Edited body",
        draft_type="fresh",
        in_reply_to=None,
        thread_id=None,
        runtime=runtime,
    )

    # The tool used its own arguments, not anything from a DB row.
    gmail_service.send_email.assert_awaited_once_with(
        to="ceo@example.com",
        subject="Edited subject",
        body="Edited body",
        in_reply_to=None,
        thread_id=None,
    )

    # The draft row was updated to "sent" with the gmail id and the diff
    # against the original draft was recorded in the edited_* columns.
    assert pending_draft.status == "sent"
    assert pending_draft.gmail_sent_id == "gmail-sent-id-42"
    assert pending_draft.edited_subject == "Edited subject"
    assert pending_draft.edited_body == "Edited body"
    assert pending_draft.edited_to is None
    db.commit.assert_awaited_once()

    # The notification carries the draft id and the gmail id.
    notification_service.broadcast.assert_awaited_once()
    event = notification_service.broadcast.await_args.args[1]
    assert event["type"] == "email_sent"
    assert event["gmail_message_id"] == "gmail-sent-id-42"
    assert event["draft_id"] == str(pending_draft_id)

    # The Command's state update clears the draft and feedback.
    update = result.update
    assert update["current_draft"] is None
    assert update["draft_feedback"] is None
    assert "Gmail message ID: gmail-sent-id-42" in update["messages"][0].content


@pytest.mark.asyncio
async def test_send_email_marks_draft_send_failed_on_gmail_error():
    gmail_service = SimpleNamespace(
        send_email=AsyncMock(side_effect=RuntimeError("gmail 500"))
    )
    notification_service = SimpleNamespace(
        create_notification=AsyncMock(),
        broadcast=AsyncMock(),
    )
    pending_draft = SimpleNamespace(
        id=uuid.uuid4(),
        to_address="ceo@example.com",
        subject="Subject",
        body="Body",
        status="pending_approval",
    )

    class _Db:
        def __init__(self):
            self.scalars = AsyncMock(return_value=SimpleNamespace(first=lambda: pending_draft))
            self.commit = AsyncMock()

    context = AgentContext(
        user_id=str(uuid.uuid4()),
        conversation_id=str(uuid.uuid4()),
        gmail_service=gmail_service,
        db_session=_Db(),
        notification_service=notification_service,
    )
    runtime = SimpleNamespace(context=context, tool_call_id="call-send-2")

    result = await send_email.coroutine(
        to="ceo@example.com",
        subject="Hello",
        body="Body",
        draft_type="fresh",
        in_reply_to=None,
        thread_id=None,
        runtime=runtime,
    )

    assert pending_draft.status == "send_failed"
    notification_service.broadcast.assert_awaited_once()
    assert notification_service.broadcast.await_args.args[1]["type"] == "error"
    assert "Failed to send email" in result.update["messages"][0].content
    assert result.update["messages"][0].status == "error"
