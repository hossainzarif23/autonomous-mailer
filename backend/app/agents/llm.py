from __future__ import annotations

from functools import lru_cache

from langchain_openrouter import ChatOpenRouter

from app.config import settings


@lru_cache
def get_llm() -> ChatOpenRouter:
    return ChatOpenRouter(
        model="qwen/qwen3.5-35b-a3b",
        temperature=0.2,
        max_tokens=4096,
        app_url=settings.APP_URL,
        app_title="Email Agent",
        api_key=settings.OPENROUTER_API_KEY,
    )
