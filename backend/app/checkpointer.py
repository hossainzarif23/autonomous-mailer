from __future__ import annotations

from contextlib import AsyncExitStack

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings

_checkpointer: AsyncPostgresSaver | None = None
_checkpointer_stack: AsyncExitStack | None = None
_checkpointer_pool: AsyncConnectionPool | None = None


async def get_checkpointer() -> AsyncPostgresSaver:
    global _checkpointer, _checkpointer_pool, _checkpointer_stack
    if _checkpointer is None:
        _checkpointer_stack = AsyncExitStack()
        _checkpointer_pool = await _checkpointer_stack.enter_async_context(
            AsyncConnectionPool(
                conninfo=settings.DATABASE_URL_PSYCOPG,
                min_size=1,
                max_size=5,
                open=False,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": None,
                    "row_factory": dict_row,
                },
            )
        )
        _checkpointer = AsyncPostgresSaver(conn=_checkpointer_pool)
    return _checkpointer


async def close_checkpointer():
    global _checkpointer, _checkpointer_pool, _checkpointer_stack
    if _checkpointer_stack is not None:
        await _checkpointer_stack.aclose()
    _checkpointer = None
    _checkpointer_pool = None
    _checkpointer_stack = None
