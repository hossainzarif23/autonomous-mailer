from __future__ import annotations

import uuid
import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

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

    def test_blocked_approval_events_return_block_then_done(self):
        draft_id = uuid.uuid4()
        conversation_id = uuid.uuid4()

        events = chat._blocked_approval_events(
            draft_id=str(draft_id),
            conversation_id=str(conversation_id),
            turn_id="turn-123",
        )

        self.assertEqual([event["type"] for event in events], ["approval_blocked", "done"])
        self.assertEqual(events[0]["draft_id"], str(draft_id))
        self.assertEqual(events[0]["conversation_id"], str(conversation_id))
        self.assertEqual(events[0]["turn_id"], "turn-123")
        self.assertEqual(events[1], {"type": "done", "turn_id": "turn-123"})


class BlockedApprovalStreamTests(IsolatedAsyncioTestCase):
    async def test_pending_approval_stream_events_emit_blocked_sequence_and_skip_auth_work(self):
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
        db = SimpleNamespace()

        with (
            patch.object(chat, "_get_pending_approval_draft", AsyncMock(return_value=draft)),
            patch.object(chat, "get_valid_access_token", AsyncMock()) as mock_get_valid_access_token,
            patch.object(chat, "get_coordinator_agent", Mock()) as mock_get_coordinator_agent,
        ):
            blocked_events = await chat._pending_approval_blocked_stream_events(
                db=db,
                user_id=draft.user_id,
                conversation_id=str(draft.conversation_id),
                turn_id="turn-123",
            )

        self.assertIsNotNone(blocked_events)
        parsed_types = [json.loads(event.split("data: ", 1)[1])["type"] for event in [chat._sse({"type": "turn_started", "turn_id": "turn-123"})] + blocked_events]
        self.assertEqual(parsed_types, ["turn_started", "approval_blocked", "done"])
        self.assertEqual(json.loads(blocked_events[0].split("data: ", 1)[1])["draft_id"], str(draft.id))
        mock_get_valid_access_token.assert_not_called()
        mock_get_coordinator_agent.assert_not_called()

    async def test_stream_chat_message_blocked_path_emits_blocked_events_and_skips_commit_and_agent_setup(self):
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
        conversation = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=draft.user_id,
            title=None,
            updated_at=None,
        )
        payload = SimpleNamespace(conversation_id=str(draft.conversation_id), message="follow up")
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(checkpointer=SimpleNamespace())))
        current_user = SimpleNamespace(id=draft.user_id)
        db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

        with (
            patch.object(chat, "_get_owned_conversation", AsyncMock(return_value=conversation)),
            patch.object(chat, "_get_pending_approval_draft", AsyncMock(return_value=draft)),
            patch.object(chat, "get_valid_access_token", AsyncMock()) as mock_get_valid_access_token,
            patch.object(chat, "get_coordinator_agent", Mock()) as mock_get_coordinator_agent,
        ):
            response = await chat.stream_chat_message(
                payload=payload,
                request=request,
                current_user=current_user,
                db=db,
            )

            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

        events = [json.loads(chunk.split("data: ", 1)[1]) for chunk in chunks if chunk.startswith("data: ")]
        self.assertEqual([event["type"] for event in events], ["turn_started", "approval_blocked", "done"])
        self.assertEqual(events[1]["draft_id"], str(draft.id))
        self.assertEqual(events[1]["conversation_id"], str(draft.conversation_id))
        db.commit.assert_not_awaited()
        self.assertIsNone(conversation.title)
        self.assertIsNone(conversation.updated_at)
        mock_get_valid_access_token.assert_not_called()
        mock_get_coordinator_agent.assert_not_called()
