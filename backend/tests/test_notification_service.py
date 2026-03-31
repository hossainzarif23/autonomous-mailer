from __future__ import annotations

from unittest import IsolatedAsyncioTestCase

from app.services.notification_service import NotificationService


class NotificationServiceTests(IsolatedAsyncioTestCase):
    async def test_broadcast_delivers_events_to_subscribers(self):
        service = NotificationService()
        queue = service.subscribe("user-1")

        await service.broadcast("user-1", {"type": "email_sent"})
        event = await queue.get()

        self.assertEqual(event["type"], "email_sent")

    async def test_unsubscribe_stops_future_delivery(self):
        service = NotificationService()
        queue = service.subscribe("user-1")
        service.unsubscribe("user-1", queue)

        await service.broadcast("user-1", {"type": "ignored"})

        self.assertTrue(queue.empty())

