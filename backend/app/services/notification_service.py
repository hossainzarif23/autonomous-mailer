from __future__ import annotations

import asyncio
from collections import defaultdict


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


notification_service = NotificationService()
