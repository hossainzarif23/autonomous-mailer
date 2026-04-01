from __future__ import annotations

import json
from typing import Any

from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, dynamic_prompt
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command
from langgraph.runtime import Runtime
from typing_extensions import NotRequired

from app.agents.context import AgentContext
from app.agents.llm import get_llm
from app.agents.mail_reader_agent import get_mail_reader_agent
from app.agents.mailing_agent import get_mailing_agent
from app.agents.tools.draft_tools import send_email
from app.agents.web_search_agent import get_web_search_agent


class EmailAgentState(AgentState[Any]):
    current_draft: NotRequired[dict[str, Any] | None]
    research_summary: NotRequired[str | None]
    draft_feedback: NotRequired[str | None]
    needs_research_refresh: NotRequired[bool]

COORDINATOR_SYSTEM_PROMPT = """
You are the central coordinator of an email assistant system. Understand the user's request
and delegate work to specialized sub-agents.

Available sub-agents:
- call_mail_reader: read, search, and summarize emails
- call_web_search: research topics before writing a fresh email
- call_mailing_agent: draft fresh emails and replies
- send_email: the final send action, which always requires human approval

Routing guidance:
- Reading, searching, or summarizing email -> call_mail_reader
- Replying to an email -> call_mailing_agent, then send_email
- Writing a fresh email about a current topic -> call_web_search first, then call_mailing_agent, then send_email
- Writing a fresh email without research -> call_mailing_agent, then send_email

Critical workflow rules:
- Always ask for missing recipient details before drafting a fresh email.
- call_mailing_agent writes the latest draft into state.current_draft and returns the draft JSON.
- state.current_draft contains keys:
  to, subject, body, draft_type, in_reply_to, thread_id
- After call_mailing_agent prepares a complete draft, call send_email with the exact values from state.current_draft.
- Never claim an email was sent unless send_email confirms success.
- If send_email is rejected, read the rejection feedback from the tool message and use state.draft_feedback while rewriting the draft.
- For a rejected fresh email, only re-run call_web_search when the feedback requires new facts, a new angle, or fresher research.
- After send_email succeeds, report the final outcome clearly.
"""


@dynamic_prompt
def coordinator_prompt(request) -> str:
    state = request.state
    draft = state.get("current_draft")
    feedback = state.get("draft_feedback")
    needs_research_refresh = state.get("needs_research_refresh")
    research_summary = state.get("research_summary")

    sections = [COORDINATOR_SYSTEM_PROMPT.strip()]
    if draft:
        sections.append(f"Current draft in state:\n{json.dumps(draft)}")
    if feedback:
        sections.append(f"Latest human feedback:\n{feedback}")
    if research_summary:
        sections.append(f"Stored research summary:\n{research_summary}")
    if needs_research_refresh:
        sections.append(
            "The current feedback likely requires refreshed or expanded research before the next draft."
        )
    return "\n\n".join(sections)


def _message_content(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in value
        ).strip()
    return str(value)


def _send_email_review_description(
    tool_call: dict,
    state: EmailAgentState,
    _runtime: Runtime[AgentContext],
) -> str:
    draft = state.get("current_draft") or tool_call.get("args", {})
    draft_type = str(draft.get("draft_type") or "fresh")
    return (
        f"Review this {draft_type} email before sending.\n\n"
        f"To: {draft.get('to', '')}\n"
        f"Subject: {draft.get('subject', '')}\n\n"
        f"{draft.get('body', '')}"
    )


def _tool_message(tool_name: str, content: str, tool_call_id: str | None) -> ToolMessage:
    return ToolMessage(
        content=content,
        name=tool_name,
        tool_call_id=tool_call_id or tool_name,
    )


def _normalize_draft(payload: dict[str, Any]) -> dict[str, Any]:
    required_keys = {"to", "subject", "body", "draft_type", "in_reply_to", "thread_id"}
    missing = required_keys.difference(payload)
    if missing:
        raise ValueError(f"Draft JSON is missing required keys: {sorted(missing)}")

    def _optional_identifier(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized or normalized.lower() in {"null", "none", "nil"}:
                return None
            return normalized
        return str(value).strip() or None

    return {
        "to": str(payload["to"]).strip(),
        "subject": str(payload["subject"]).strip(),
        "body": str(payload["body"]).strip(),
        "draft_type": str(payload["draft_type"]).strip(),
        "in_reply_to": _optional_identifier(payload["in_reply_to"]),
        "thread_id": _optional_identifier(payload["thread_id"]),
    }


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
        summary = _message_content(result["messages"][-1].content)
        return Command(
            update={
                "research_summary": summary,
                "needs_research_refresh": False,
                "messages": [
                    _tool_message("call_web_search", summary, runtime.tool_call_id)
                ],
            }
        )

    @tool
    async def call_mailing_agent(task: str, runtime: ToolRuntime[AgentContext]) -> str:
        """Delegate drafting work to the mailing agent and persist the draft in state."""
        state = runtime.state
        draft_feedback = state.get("draft_feedback")
        research_summary = state.get("research_summary")
        current_draft = state.get("current_draft")

        prompt_parts = [task.strip()]
        if research_summary:
            prompt_parts.append(f"Research summary:\n{research_summary}")
        if current_draft:
            prompt_parts.append(f"Current draft JSON:\n{json.dumps(current_draft)}")
        if draft_feedback:
            prompt_parts.append(f"Human feedback for the rewrite:\n{draft_feedback}")

        result = await mailing_agent.ainvoke(
            {"messages": [HumanMessage(content="\n\n".join(part for part in prompt_parts if part))]},
            context=runtime.context,
            config={"configurable": {"thread_id": f"mailing_{runtime.context.user_id}"}},
        )
        content = _message_content(result["messages"][-1].content)
        draft = _normalize_draft(json.loads(content))
        return Command(
            update={
                "current_draft": draft,
                "draft_feedback": None,
                "messages": [
                    _tool_message("call_mailing_agent", json.dumps(draft), runtime.tool_call_id)
                ],
            }
        )

    return [call_mail_reader, call_web_search, call_mailing_agent, send_email]


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
            state_schema=EmailAgentState,
            context_schema=AgentContext,
            checkpointer=checkpointer,
            middleware=[
                coordinator_prompt,
                HumanInTheLoopMiddleware(
                    interrupt_on={
                        "send_email": {
                            "allowed_decisions": ["approve", "edit", "reject"],
                            "description": _send_email_review_description,
                        }
                    }
                )
            ],
            name="coordinator",
        )
        _coordinator_checkpointer_id = current_checkpointer_id
    return _coordinator_agent
