from __future__ import annotations

from contextlib import AsyncExitStack

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import settings

_checkpointer: AsyncPostgresSaver | None = None
_checkpointer_stack: AsyncExitStack | None = None


async def get_checkpointer() -> AsyncPostgresSaver:
    global _checkpointer, _checkpointer_stack
    if _checkpointer is None:
        _checkpointer_stack = AsyncExitStack()
        _checkpointer = await _checkpointer_stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(settings.DATABASE_URL_PSYCOPG)
        )
    return _checkpointer


async def close_checkpointer():
    global _checkpointer, _checkpointer_stack
    if _checkpointer_stack is not None:
        await _checkpointer_stack.aclose()
    _checkpointer = None
    _checkpointer_stack = None
