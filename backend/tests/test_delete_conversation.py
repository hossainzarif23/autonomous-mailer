from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, status

from app.routers import chat


def _make_request():
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(checkpointer=AsyncMock()))
    )


def _make_user(user_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=user_id or uuid.uuid4())


def _make_conversation(owner_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), user_id=owner_id, title="Test")


@pytest.mark.asyncio
async def test_delete_conversation_returns_204_and_cascades_to_drafts_and_checkpoints():
    owner_id = uuid.uuid4()
    conversation = _make_conversation(owner_id)
    conversation_id = str(conversation.id)
    current_user = _make_user(owner_id)
    request = _make_request()

    drafts_result = SimpleNamespace(all=lambda: [SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4())])
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=drafts_result),
        get=AsyncMock(return_value=conversation),
        delete=AsyncMock(),
        commit=AsyncMock(),
    )

    with (
        patch.object(chat, "_get_owned_conversation", AsyncMock(return_value=conversation)) as mock_owned,
    ):
        response = await chat.delete_conversation(
            conversation_id=conversation_id,
            request=request,
            current_user=current_user,
            db=db,
        )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    mock_owned.assert_awaited_once_with(db, conversation_id, current_user.id)
    db.scalars.assert_awaited_once()
    assert db.delete.await_count == 3
    db.commit.assert_awaited_once()
    request.app.state.checkpointer.adelete_thread.assert_awaited_once_with(
        {"configurable": {"thread_id": conversation_id}}
    )


@pytest.mark.asyncio
async def test_delete_conversation_propagates_owner_check_404():
    owner_id = uuid.uuid4()
    conversation = _make_conversation(owner_id)
    conversation_id = str(conversation.id)
    current_user = _make_user(owner_id)
    request = _make_request()

    db = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [])),
        delete=AsyncMock(),
        commit=AsyncMock(),
    )

    with patch.object(
        chat,
        "_get_owned_conversation",
        AsyncMock(side_effect=HTTPException(status_code=404, detail="Conversation not found")),
    ) as mock_owned:
        with pytest.raises(HTTPException) as exc:
            await chat.delete_conversation(
                conversation_id=conversation_id,
                request=request,
                current_user=current_user,
                db=db,
            )

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    mock_owned.assert_awaited_once_with(db, conversation_id, current_user.id)
    db.delete.assert_not_called()
    db.commit.assert_not_called()
    request.app.state.checkpointer.adelete_thread.assert_not_called()


@pytest.mark.asyncio
async def test_delete_conversation_works_when_no_drafts_exist():
    owner_id = uuid.uuid4()
    conversation = _make_conversation(owner_id)
    conversation_id = str(conversation.id)
    current_user = _make_user(owner_id)
    request = _make_request()

    db = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [])),
        delete=AsyncMock(),
        commit=AsyncMock(),
    )

    with patch.object(chat, "_get_owned_conversation", AsyncMock(return_value=conversation)):
        response = await chat.delete_conversation(
            conversation_id=conversation_id,
            request=request,
            current_user=current_user,
            db=db,
        )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert db.delete.await_count == 1
    db.delete.assert_awaited_once_with(conversation)
    db.commit.assert_awaited_once()
    request.app.state.checkpointer.adelete_thread.assert_awaited_once_with(
        {"configurable": {"thread_id": conversation_id}}
    )
