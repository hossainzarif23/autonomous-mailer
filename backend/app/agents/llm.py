from __future__ import annotations

import os
from functools import lru_cache

from langchain_openrouter import ChatOpenRouter

from app.config import settings


@lru_cache
def get_llm() -> ChatOpenRouter:
    if settings.LANGSMITH_TRACING:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGSMITH_PROJECT"] = settings.LANGSMITH_PROJECT
        os.environ["LANGSMITH_ENDPOINT"] = settings.LANGSMITH_ENDPOINT
        if settings.LANGSMITH_API_KEY:
            os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY

    return ChatOpenRouter(
        model="qwen/qwen3.6-plus-preview:free",
        temperature=0.1,
        max_tokens=4096,
        app_url=settings.APP_URL,
        app_title="Email Agent",
        api_key=settings.OPENROUTER_API_KEY,
    )
