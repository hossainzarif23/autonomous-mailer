from __future__ import annotations

from langchain.agents import create_agent

from app.agents.context import AgentContext
from app.agents.llm import get_llm
from app.agents.tools.gmail_tools import (
    get_email_thread,
    get_full_email,
    get_recent_emails,
    search_emails_by_sender,
    search_emails_by_topic,
)

MAIL_READER_SYSTEM_PROMPT = """
You are a specialized email reading assistant with read-only access to the user's Gmail.
Your responsibilities:
- Fetch and display recent emails when asked
- Search emails by sender name or email address
- Search emails by topic, keyword, or subject
- Summarize individual emails or complete threads
- Extract key information such as sender, date, main points, and action items

Always present emails clearly and concisely.
Never attempt to send, draft, or modify any email.
"""

_mail_reader_agent = None
_mail_reader_checkpointer_id = None


def get_mail_reader_agent(checkpointer=None):
    global _mail_reader_agent, _mail_reader_checkpointer_id
    current_checkpointer_id = id(checkpointer) if checkpointer is not None else None
    if _mail_reader_agent is None or _mail_reader_checkpointer_id != current_checkpointer_id:
        _mail_reader_agent = create_agent(
            model=get_llm(),
            tools=[
                get_recent_emails,
                search_emails_by_sender,
                search_emails_by_topic,
                get_email_thread,
                get_full_email,
            ],
            system_prompt=MAIL_READER_SYSTEM_PROMPT,
            context_schema=AgentContext,
            checkpointer=checkpointer,
            name="mail_reader_agent",
        )
        _mail_reader_checkpointer_id = current_checkpointer_id
    return _mail_reader_agent
