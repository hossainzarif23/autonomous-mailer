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
async def get_recent_emails(count: int, runtime: ToolRuntime[AgentContext]) -> str:
    """Fetch the user's most recent emails."""
    gmail = runtime.context.gmail_service
    emails = await gmail.list_messages(max_results=max(1, min(count, 20)))
    return _format_email_list(emails)


@tool
async def search_emails_by_sender(sender: str, runtime: ToolRuntime[AgentContext]) -> str:
    """Search the user's Gmail for emails from a sender."""
    gmail = runtime.context.gmail_service
    query = gmail._build_query(sender=sender)
    emails = await gmail.list_messages(query=query, max_results=10)
    return _format_email_list(emails)


@tool
async def search_emails_by_topic(topic: str, runtime: ToolRuntime[AgentContext]) -> str:
    """Search the user's Gmail for emails about a topic or keyword."""
    gmail = runtime.context.gmail_service
    query = gmail._build_query(topic=topic)
    emails = await gmail.list_messages(query=query, max_results=10)
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
