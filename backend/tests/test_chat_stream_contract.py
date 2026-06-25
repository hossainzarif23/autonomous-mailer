from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.models.email_draft import EmailDraft
from app.routers import chat


@pytest.mark.asyncio
async def test_get_pending_approval_draft_returns_first_matching_draft():
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

    assert result is draft
    db.scalars.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_pending_approval_draft_returns_none_when_no_match():
    scalars_result = SimpleNamespace(first=lambda: None)
    db = SimpleNamespace(scalars=AsyncMock(return_value=scalars_result))

    result = await chat._get_pending_approval_draft(
        db,
        user_id=uuid.uuid4(),
        conversation_id=str(uuid.uuid4()),
    )

    assert result is None
    db.scalars.assert_awaited_once()


def test_approval_blocked_event_has_user_safe_shape():
    draft_id = uuid.uuid4()
    conversation_id = uuid.uuid4()

    event = chat._approval_blocked_event(
        draft_id=str(draft_id),
        conversation_id=str(conversation_id),
        turn_id="turn-123",
    )

    assert event["type"] == "approval_blocked"
    assert event["draft_id"] == str(draft_id)
    assert event["conversation_id"] == str(conversation_id)
    assert event["turn_id"] == "turn-123"
    assert "pending draft" in event["content"].lower()
    assert "{" not in event["content"]


def test_blocked_approval_events_return_block_then_done():
    draft_id = uuid.uuid4()
    conversation_id = uuid.uuid4()

    events = chat._blocked_approval_events(
        draft_id=str(draft_id),
        conversation_id=str(conversation_id),
        turn_id="turn-123",
    )

    assert [event["type"] for event in events] == ["approval_blocked", "done"]
    assert events[0]["draft_id"] == str(draft_id)
    assert events[0]["conversation_id"] == str(conversation_id)
    assert events[0]["turn_id"] == "turn-123"
    assert events[1] == {"type": "done", "turn_id": "turn-123"}


@pytest.mark.asyncio
async def test_pending_approval_stream_events_emit_blocked_sequence_and_skip_auth_work():
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

    assert blocked_events is not None
    parsed_types = [json.loads(event.split("data: ", 1)[1])["type"] for event in [chat._sse({"type": "turn_started", "turn_id": "turn-123"})] + blocked_events]
    assert parsed_types == ["turn_started", "approval_blocked", "done"]
    assert json.loads(blocked_events[0].split("data: ", 1)[1])["draft_id"] == str(draft.id)
    mock_get_valid_access_token.assert_not_called()
    mock_get_coordinator_agent.assert_not_called()


@pytest.mark.asyncio
async def test_stream_chat_message_blocked_path_emits_blocked_events_and_skips_commit_and_agent_setup():
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
    assert [event["type"] for event in events] == ["turn_started", "approval_blocked", "done"]
    assert events[1]["draft_id"] == str(draft.id)
    assert events[1]["conversation_id"] == str(draft.conversation_id)
    db.commit.assert_not_awaited()
    assert conversation.title is None
    assert conversation.updated_at is None
    mock_get_valid_access_token.assert_not_called()
    mock_get_coordinator_agent.assert_not_called()


@pytest.mark.asyncio
async def test_stream_chat_message_emits_distinct_fallback_tool_call_ids_for_repeated_idless_calls():
    payload = SimpleNamespace(conversation_id=str(uuid.uuid4()), message="research AI")
    current_user = SimpleNamespace(id=uuid.uuid4())
    conversation = SimpleNamespace(
        id=uuid.UUID(payload.conversation_id),
        user_id=current_user.id,
        title=None,
        updated_at=None,
    )
    db = SimpleNamespace(commit=AsyncMock())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(checkpointer=object())))

    async def fake_astream(*_args, **_kwargs):
        yield {
            "type": "messages",
            "data": [
                SimpleNamespace(
                    content="",
                    tool_calls=[{"name": "call_web_search", "args": {"topic": "AI"}}],
                ),
                {},
            ],
        }
        yield {
            "type": "messages",
            "data": [
                SimpleNamespace(
                    content="",
                    tool_calls=[{"name": "call_web_search", "args": {"topic": "AI"}}],
                ),
                {},
            ],
        }
        yield {
            "type": "updates",
            "data": {
                "node": {
                    "messages": [
                        chat.ToolMessage(
                            content='{"secret":"raw"}',
                            name="call_web_search",
                            tool_call_id="",
                        ),
                        chat.ToolMessage(
                            content='{"secret":"raw-duplicate"}',
                            name="call_web_search",
                            tool_call_id="",
                        ),
                    ]
                }
            },
        }

    fake_coordinator = SimpleNamespace(astream=fake_astream)

    with (
        patch.object(chat, "_get_owned_conversation", AsyncMock(return_value=conversation)),
        patch.object(chat, "_get_pending_approval_draft", AsyncMock(return_value=None)),
        patch.object(chat, "get_valid_access_token", AsyncMock(return_value="access-token")),
        patch.object(chat, "GmailService", Mock(return_value=SimpleNamespace())),
        patch.object(chat, "get_coordinator_agent", Mock(return_value=fake_coordinator)),
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
    event_types = [event["type"] for event in events]
    assert event_types.count("action_started") == 2
    assert event_types.count("action_completed") == 2

    action_started_events = [event for event in events if event["type"] == "action_started"]
    action_completed_events = [event for event in events if event["type"] == "action_completed"]
    assert all(event["tool_call_id"].startswith("generated:") for event in action_started_events)
    assert len({event["tool_call_id"] for event in action_started_events}) == 2
    assert [event["tool_call_id"] for event in action_completed_events] == [
        event["tool_call_id"] for event in action_started_events
    ]


@pytest.mark.asyncio
async def test_stream_chat_message_preserves_tool_call_ids_and_filters_raw_tool_payloads():
    payload = SimpleNamespace(conversation_id=str(uuid.uuid4()), message="research AI")
    current_user = SimpleNamespace(id=uuid.uuid4())
    conversation = SimpleNamespace(
        id=uuid.UUID(payload.conversation_id),
        user_id=current_user.id,
        title=None,
        updated_at=None,
    )
    db = SimpleNamespace(commit=AsyncMock())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(checkpointer=object())))

    async def fake_astream(*_args, **_kwargs):
        yield {
            "type": "messages",
            "data": [
                SimpleNamespace(
                    content="",
                    tool_calls=[{"name": "call_web_search", "id": "call-1", "args": {"topic": "AI"}}],
                ),
                {},
            ],
        }
        yield {
            "type": "messages",
            "data": [
                SimpleNamespace(
                    content="",
                    tool_calls=[{"name": "call_web_search", "id": "call-1", "args": {"topic": "AI again"}}],
                ),
                {},
            ],
        }
        yield {
            "type": "messages",
            "data": [
                SimpleNamespace(
                    content='{"query":"AI","results":[{"url":"https://example.com"}]}',
                    tool_calls=[],
                ),
                {},
            ],
        }
        yield {
            "type": "messages",
            "data": [
                SimpleNamespace(content="Safe final prose.", tool_calls=[]),
                {},
            ],
        }
        yield {
            "type": "updates",
            "data": {
                "node": {
                    "messages": [
                        chat.ToolMessage(
                            content='{"secret":"raw"}',
                            name="call_web_search",
                            tool_call_id="call-1",
                        ),
                        chat.ToolMessage(
                            content='{"secret":"raw-duplicate"}',
                            name="call_web_search",
                            tool_call_id="call-1",
                        ),
                    ]
                }
            },
        }

    fake_coordinator = SimpleNamespace(astream=fake_astream)

    with (
        patch.object(chat, "_get_owned_conversation", AsyncMock(return_value=conversation)),
        patch.object(chat, "_get_pending_approval_draft", AsyncMock(return_value=None)),
        patch.object(chat, "get_valid_access_token", AsyncMock(return_value="access-token")),
        patch.object(chat, "GmailService", Mock(return_value=SimpleNamespace())),
        patch.object(chat, "get_coordinator_agent", Mock(return_value=fake_coordinator)),
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
    event_types = [event["type"] for event in events]
    assert event_types.count("action_started") == 1
    assert event_types.count("action_completed") == 1
    assert "turn_completed" in event_types
    assert "done" in event_types

    token_contents = [event["content"] for event in events if event["type"] == "token"]
    assert token_contents == ["Safe final prose."]

    action_started = next(event for event in events if event["type"] == "action_started")
    action_completed = next(event for event in events if event["type"] == "action_completed")
    assert action_started["tool_call_id"] == "call-1"
    assert action_completed["tool_call_id"] == "call-1"


def test_tool_call_chunks_do_not_emit_tokens():
    chunk = SimpleNamespace(
        content="",
        tool_calls=[
            {
                "name": "call_web_search",
                "args": {"topic": "AI trends"},
            }
        ],
    )

    assert chat._safe_token_content(chunk) is None


def test_json_payload_chunks_do_not_emit_tokens():
    chunk = SimpleNamespace(
        content='{"query":"AI trends","results":[{"url":"https://example.com"}]}',
        tool_calls=[],
    )

    assert chat._safe_token_content(chunk) is None


def test_plain_assistant_text_can_emit_tokens():
    chunk = SimpleNamespace(content="Here is a concise answer.", tool_calls=[])

    assert chat._safe_token_content(chunk) == "Here is a concise answer."


def test_action_event_for_known_tool_update():
    event = chat._action_started_event("call_web_search", turn_id="turn-123")

    assert event["type"] == "action_started"
    assert event["tool"] == "call_web_search"
    assert event["label"] == "Research completed"
    assert event["turn_id"] == "turn-123"


def test_action_completed_event_for_known_tool_update():
    event = chat._action_completed_event("call_web_search", turn_id="turn-123")

    assert event["type"] == "action_completed"
    assert event["tool"] == "call_web_search"
    assert event["label"] == "Research completed"
    assert event["turn_id"] == "turn-123"


def test_tool_call_names_extracts_dict_tool_calls():
    chunk = SimpleNamespace(
        content="",
        tool_calls=[
            {"name": "call_web_search", "args": {"topic": "AI trends"}},
            {"name": "call_mailing_agent", "args": {"task": "Draft"}},
        ],
    )

    assert chat._tool_call_names(chunk) == ["call_web_search", "call_mailing_agent"]


def test_tool_call_detail_generates_fallback_id_for_idless_dict_tool_call():
    name, tool_call_id = chat._tool_call_detail(
        {"name": "call_web_search", "args": {"topic": "AI trends"}},
        turn_id="turn-123",
        occurrence_index=1,
    )

    assert name == "call_web_search"
    assert tool_call_id.startswith("generated:turn-123:")
