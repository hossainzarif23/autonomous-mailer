from __future__ import annotations

from langchain.agents import create_agent

from app.agents.context import AgentContext
from app.agents.llm import get_llm
from app.agents.tools.search_tools import web_search

WEB_SEARCH_SYSTEM_PROMPT = """
You are a research agent. Gather relevant, accurate, up-to-date information from the web
to help compose a professional email.

When given a topic:
1. Search for recent developments, key facts, and relevant data
2. Identify 3-5 strong talking points
3. Note relevant statistics or credible sources

Return concise, structured research rather than drafting the final email.
"""

_web_search_agent = None
_web_search_checkpointer_id = None


def get_web_search_agent(checkpointer=None):
    global _web_search_agent, _web_search_checkpointer_id
    current_checkpointer_id = id(checkpointer) if checkpointer is not None else None
    if _web_search_agent is None or _web_search_checkpointer_id != current_checkpointer_id:
        _web_search_agent = create_agent(
            model=get_llm(),
            tools=[web_search],
            system_prompt=WEB_SEARCH_SYSTEM_PROMPT,
            context_schema=AgentContext,
            checkpointer=checkpointer,
            name="web_search_agent",
        )
        _web_search_checkpointer_id = current_checkpointer_id
    return _web_search_agent
