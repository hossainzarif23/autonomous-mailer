from __future__ import annotations

import os
from functools import lru_cache

from langchain_google_genai import ChatGoogleGenerativeAI


@lru_cache
def get_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        temperature=0.7,
        top_p=0.95,
        top_k=40,
        max_output_tokens=32768,
        thinking_level="medium",
    )
