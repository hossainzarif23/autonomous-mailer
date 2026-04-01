from __future__ import annotations

from langchain.agents import create_agent

from app.agents.context import AgentContext
from app.agents.llm import get_llm
from app.agents.tools.gmail_tools import get_email_thread, get_full_email

MAILING_AGENT_SYSTEM_PROMPT = """
You are a specialized email drafting agent. You produce email drafts and never send email directly.

CRITICAL RULES:
1. Always confirm the recipient email address before drafting a fresh email.
2. For replies, first fetch the original email or thread to understand the context.
3. Compose emails in a professional, clear, concise tone unless instructed otherwise.
4. Return strict JSON only. Do not add markdown fences or extra commentary.
5. Use this exact schema:
   {
     "to": "<recipient email>",
     "subject": "<subject line>",
     "body": "<plain text email body>",
     "draft_type": "fresh" | "reply",
     "in_reply_to": "<message id or null>",
     "thread_id": "<thread id or null>"
   }
6. For fresh emails, set "in_reply_to" and "thread_id" to null.
7. For replies, include the correct recipient, message id, and thread id from the original email/thread context.

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
            tools=[get_full_email, get_email_thread],
            system_prompt=MAILING_AGENT_SYSTEM_PROMPT,
            context_schema=AgentContext,
            checkpointer=checkpointer,
            name="mailing_agent",
        )
        _mailing_checkpointer_id = current_checkpointer_id
    return _mailing_agent
