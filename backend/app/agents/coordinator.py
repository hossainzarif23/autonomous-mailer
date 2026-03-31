from __future__ import annotations

from langchain.agents import create_agent
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import HumanMessage

from app.agents.context import AgentContext
from app.agents.llm import get_llm
from app.agents.mail_reader_agent import get_mail_reader_agent
from app.agents.mailing_agent import get_mailing_agent
from app.agents.web_search_agent import get_web_search_agent

COORDINATOR_SYSTEM_PROMPT = """
You are the central coordinator of an email assistant system. Understand the user's request
and delegate work to specialized sub-agents.

Available sub-agents:
- call_mail_reader: read, search, and summarize emails
- call_web_search: research topics before writing a fresh email
- call_mailing_agent: compose, reply to, and send emails

Routing guidance:
- Reading, searching, or summarizing email -> call_mail_reader
- Replying to an email -> call_mailing_agent
- Writing a fresh email about a current topic -> call_web_search first, then call_mailing_agent
- Writing a fresh email without research -> call_mailing_agent directly

Always ask for missing recipient details before requesting a fresh email draft.
Always report the final outcome clearly.
"""


def _message_content(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in value
        ).strip()
    return str(value)


def make_coordinator_tools(checkpointer):
    mail_reader = get_mail_reader_agent(checkpointer)
    web_search_agent = get_web_search_agent(checkpointer)
    mailing_agent = get_mailing_agent(checkpointer)

    @tool
    async def call_mail_reader(task: str, runtime: ToolRuntime[AgentContext]) -> str:
        """Delegate email reading, searching, or summarization to the mail reader agent."""
        result = await mail_reader.ainvoke(
            {"messages": [HumanMessage(content=task)]},
            context=runtime.context,
            config={"configurable": {"thread_id": f"mail_reader_{runtime.context.user_id}"}},
        )
        return _message_content(result["messages"][-1].content)

    @tool
    async def call_web_search(topic: str, runtime: ToolRuntime[AgentContext]) -> str:
        """Delegate web research for a topic to the web search agent."""
        result = await web_search_agent.ainvoke(
            {"messages": [HumanMessage(content=f"Research this topic for an email: {topic}")]},
            context=runtime.context,
            config={"configurable": {"thread_id": f"search_{runtime.context.user_id}"}},
        )
        return _message_content(result["messages"][-1].content)

    @tool
    async def call_mailing_agent(task: str, runtime: ToolRuntime[AgentContext]) -> str:
        """Delegate drafting, replying, or sending tasks to the mailing agent."""
        result = await mailing_agent.ainvoke(
            {"messages": [HumanMessage(content=task)]},
            context=runtime.context,
            config={"configurable": {"thread_id": f"mailing_{runtime.context.user_id}"}},
        )
        return _message_content(result["messages"][-1].content)

    return [call_mail_reader, call_web_search, call_mailing_agent]


_coordinator_agent = None
_coordinator_checkpointer_id = None


def get_coordinator_agent(checkpointer):
    global _coordinator_agent, _coordinator_checkpointer_id
    current_checkpointer_id = id(checkpointer) if checkpointer is not None else None
    if _coordinator_agent is None or _coordinator_checkpointer_id != current_checkpointer_id:
        _coordinator_agent = create_agent(
            model=get_llm(),
            tools=make_coordinator_tools(checkpointer),
            system_prompt=COORDINATOR_SYSTEM_PROMPT,
            context_schema=AgentContext,
            checkpointer=checkpointer,
            name="coordinator",
        )
        _coordinator_checkpointer_id = current_checkpointer_id
    return _coordinator_agent
