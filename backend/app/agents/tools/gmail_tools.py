from __future__ import annotations

from langchain.tools import ToolRuntime, tool

from app.agents.context import AgentContext


def _format_email_list(emails: list[dict]) -> str:
    if not emails:
        return "No matching emails were found."

    rows = []
    for index, email in enumerate(emails, start=1):
        rows.append(
            "\n".join(
                [
                    f"{index}. Subject: {email['subject'] or '(no subject)'}",
                    f"   From: {email['from_name']} <{email['from_email']}>",
                    f"   Date: {email['date']}",
                    f"   Message ID: {email['message_id']}",
                    f"   Thread ID: {email['thread_id']}",
                    f"   Snippet: {email['snippet']}",
                ]
            )
        )
    return "\n\n".join(rows)


def _format_thread(thread: dict) -> str:
    messages = thread.get("messages", [])
    if not messages:
        return "The thread is empty."

    header = f"Thread ID: {thread['thread_id']}\nMessages: {len(messages)}"
    return header + "\n\n" + _format_email_list(messages)


def _format_full_email(email: dict) -> str:
    return "\n".join(
        [
            f"Subject: {email['subject'] or '(no subject)'}",
            f"From: {email['from_name']} <{email['from_email']}>",
            f"To: {email['to']}",
            f"Date: {email['date']}",
            f"Message ID: {email['message_id']}",
            f"Thread ID: {email['thread_id']}",
            "",
            email["body"] or email["snippet"] or "(empty body)",
        ]
    )


@tool
async def get_emails(
    sender: str | None = None,
    topic: str | None = None,
    count: int = 5,
    runtime: ToolRuntime[AgentContext] = None,
) -> str:
    """Fetch the user's most recent emails. When the user names a sender, you MUST pass it via the `sender` parameter as a Gmail search term (e.g. "linkedin.com" or "alice@x.com"). Never retry without the filter if it returns 0 results — report the empty result instead of substituting other emails.

    Args:
        sender: If provided, restrict to emails from this sender (e.g. "Alice" or "alice@x.com").
        topic: If provided, restrict to emails about this topic/keyword.
        count: Maximum number of recent emails to return (1-20, default 5).

    When neither sender nor topic is given, returns the user's `count` most recent
    emails. When either is given, composes a Gmail query and returns matching
    emails. Combinations are joined as a Gmail search query.
    """
    gmail = runtime.context.gmail_service
    query = gmail._build_query(sender=sender, topic=topic)
    emails = await gmail.list_messages(query=query, max_results=max(1, min(count, 20)))
    return _format_email_list(emails)


@tool
async def get_email_thread(thread_id: str, runtime: ToolRuntime[AgentContext]) -> str:
    """Fetch and format a full Gmail thread."""
    gmail = runtime.context.gmail_service
    thread = await gmail.get_thread(thread_id)
    return _format_thread(thread)


@tool
async def get_full_email(message_id: str, runtime: ToolRuntime[AgentContext]) -> str:
    """Fetch and format a full Gmail message by message ID."""
    gmail = runtime.context.gmail_service
    email = await gmail.get_message(message_id)
    return _format_full_email(email)
