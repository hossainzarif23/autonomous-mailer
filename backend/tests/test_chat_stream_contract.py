from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

from app.models.email_draft import EmailDraft
from app.routers import chat


class PendingApprovalGuardTests(IsolatedAsyncioTestCase):
    async def test_get_pending_approval_draft_returns_first_matching_draft(self):
        draft = EmailDraft(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            draft_type="fresh",
            to_address="recipient@example.com",
            subject="Subject",
            body="Body",
            status="pending_approval",
        )
        scalars_result = SimpleNamespace(first=lambda: draft)
        db = SimpleNamespace(scalars=AsyncMock(return_value=scalars_result))

        result = await chat._get_pending_approval_draft(
            db,
            user_id=draft.user_id,
            conversation_id=str(draft.conversation_id),
        )

        self.assertIs(result, draft)
        db.scalars.assert_awaited_once()

    async def test_get_pending_approval_draft_returns_none_when_no_match(self):
        scalars_result = SimpleNamespace(first=lambda: None)
        db = SimpleNamespace(scalars=AsyncMock(return_value=scalars_result))

        result = await chat._get_pending_approval_draft(
            db,
            user_id=uuid.uuid4(),
            conversation_id=str(uuid.uuid4()),
        )

        self.assertIsNone(result)
        db.scalars.assert_awaited_once()


class ApprovalBlockedEventTests(TestCase):
    def test_approval_blocked_event_has_user_safe_shape(self):
        draft_id = uuid.uuid4()
        conversation_id = uuid.uuid4()

        event = chat._approval_blocked_event(
            draft_id=str(draft_id),
            conversation_id=str(conversation_id),
            turn_id="turn-123",
        )

        self.assertEqual(event["type"], "approval_blocked")
        self.assertEqual(event["draft_id"], str(draft_id))
        self.assertEqual(event["conversation_id"], str(conversation_id))
        self.assertEqual(event["turn_id"], "turn-123")
        self.assertIn("pending draft", event["content"].lower())
        self.assertNotIn("{", event["content"])
