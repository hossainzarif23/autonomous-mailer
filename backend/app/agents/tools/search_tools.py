from __future__ import annotations

from functools import lru_cache
from typing import Any

from langchain.tools import tool
from tavily import TavilyClient

from app.config import settings


@lru_cache
def get_tavily_client() -> TavilyClient:
    return TavilyClient(api_key=settings.TAVILY_API_KEY)


@tool
def web_search(query: str) -> dict[str, Any]:
    """Search the web for current information to support email composition."""
    try:
        return get_tavily_client().search(
            query=query,
            search_depth="advanced",
            topic="general",
            max_results=5,
            include_answer="advanced",
        )
    except Exception as exc:
        return {"error": str(exc), "query": query}
