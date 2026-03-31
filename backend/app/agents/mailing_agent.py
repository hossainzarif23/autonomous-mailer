from __future__ import annotations

from langchain.agents import create_agent

from app.agents.context import AgentContext
from app.agents.llm import get_llm
from app.agents.tools.draft_tools import compose_and_request_approval
from app.agents.tools.gmail_tools import get_email_thread, get_full_email

MAILING_AGENT_SYSTEM_PROMPT = """
You are a specialized email composition agent. You draft and send emails on behalf of the user.

CRITICAL RULES:
1. Never send an email without calling compose_and_request_approval.
2. Always confirm the recipient email address before drafting.
3. For replies, first fetch the original email or thread to understand the context.
4. Compose emails in a professional, clear, concise tone unless instructed otherwise.
5. After compose_and_request_approval returns, report the outcome clearly.

For fresh emails using research:
- Use the provided research data to craft the email body.
- Write a natural email, not a bullet list of findings.
- Suggest a clear subject line.
"""

_mailing_agent = None
_mailing_checkpointer_id = None


def get_mailing_agent(checkpointer=None):
    global _mailing_agent, _mailing_checkpointer_id
    current_checkpointer_id = id(checkpointer) if checkpointer is not None else None
    if _mailing_agent is None or _mailing_checkpointer_id != current_checkpointer_id:
        _mailing_agent = create_agent(
            model=get_llm(),
            tools=[get_full_email, get_email_thread, compose_and_request_approval],
            system_prompt=MAILING_AGENT_SYSTEM_PROMPT,
            context_schema=AgentContext,
            checkpointer=checkpointer,
            name="mailing_agent",
        )
        _mailing_checkpointer_id = current_checkpointer_id
    return _mailing_agent
