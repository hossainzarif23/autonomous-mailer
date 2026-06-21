from __future__ import annotations

import os
from functools import lru_cache

# from langchain_openrouter import ChatOpenRouter
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings


@lru_cache
def get_llm() -> ChatGoogleGenerativeAI:
    if settings.LANGSMITH_TRACING:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGSMITH_PROJECT"] = settings.LANGSMITH_PROJECT
        os.environ["LANGSMITH_ENDPOINT"] = settings.LANGSMITH_ENDPOINT
        if settings.LANGSMITH_API_KEY:
            os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY

    return ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        temperature=0.7,
        top_p=0.95,
        top_k=40,
        max_output_tokens=32768,
        thinking_level="medium",
    )
