from __future__ import annotations

import pytest

from app.services.notification_service import NotificationService


@pytest.mark.asyncio
async def test_broadcast_delivers_events_to_subscribers():
    service = NotificationService()
    queue = service.subscribe("user-1")

    await service.broadcast("user-1", {"type": "email_sent"})
    event = await queue.get()

    assert event["type"] == "email_sent"


@pytest.mark.asyncio
async def test_unsubscribe_stops_future_delivery():
    service = NotificationService()
    queue = service.subscribe("user-1")
    service.unsubscribe("user-1", queue)

    await service.broadcast("user-1", {"type": "ignored"})

    assert queue.empty()
