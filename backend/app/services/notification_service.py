from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification


class NotificationService:
    """
    Per-user async event broadcaster.
    This is used by Phase 4 draft tooling and becomes the SSE backbone in Phase 5.
    """

    def __init__(self):
        self._queues: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, user_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._queues[user_id].append(queue)
        return queue

    def unsubscribe(self, user_id: str, queue: asyncio.Queue):
        try:
            self._queues[user_id].remove(queue)
        except ValueError:
            pass

    async def broadcast(self, user_id: str, event: dict):
        for queue in list(self._queues.get(user_id, [])):
            await queue.put(event)

    async def create_notification(
        self,
        db: AsyncSession,
        user_id: str,
        *,
        type: str,
        title: str,
        body: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Notification:
        notification = Notification(
            user_id=uuid.UUID(user_id),
            type=type,
            title=title,
            body=body,
            metadata_json=metadata or {},
        )
        db.add(notification)
        await db.commit()
        await db.refresh(notification)
        return notification


notification_service = NotificationService()
