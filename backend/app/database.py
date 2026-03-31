from __future__ import annotations

from collections.abc import AsyncGenerator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


def _build_async_engine_config(database_url: str) -> tuple[str, dict]:
    """
    Normalize asyncpg URL query params into typed connect_args.
    SQLAlchemy forwards URL query params as strings, but asyncpg expects
    native values for options like timeout.
    """
    split_url = urlsplit(database_url)
    query_params = dict(parse_qsl(split_url.query, keep_blank_values=True))
    connect_args: dict[str, object] = {}

    ssl_value = query_params.pop("ssl", None)
    if ssl_value is not None:
        connect_args["ssl"] = ssl_value

    timeout_value = query_params.pop("timeout", None)
    if timeout_value is not None:
        connect_args["timeout"] = float(timeout_value)

    normalized_url = urlunsplit(
        (split_url.scheme, split_url.netloc, split_url.path, urlencode(query_params), split_url.fragment)
    )
    return normalized_url, connect_args


engine_url, engine_connect_args = _build_async_engine_config(settings.DATABASE_URL)

engine = create_async_engine(
    engine_url,
    connect_args=engine_connect_args,
    echo=settings.APP_ENV == "development",
    future=True,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
