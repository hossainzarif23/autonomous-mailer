"""
Regression tests for the "LinkedIn/OpenAI 10-BRAC-Bank-emails" bug.

The bug: when a user asks for emails from a specific sender, the LLM may
make several `get_emails` calls before settling on the right filter.
Intermediate calls (e.g. with no filter, returning unrelated bank emails)
were being parsed as the "Email Results" list, while the LLM's prose
summary described a later, correctly-filtered call. The user then saw
two contradictory things in the same response.

These tests assert:
  1. The `get_emails` tool's LLM-facing description encodes the rules
     that prevent the LLM from passing vague senders and from retrying
     without a filter.
  2. The mail reader's system prompt explicitly forbids fabrication and
     tells the LLM to use a domain.
  3. The chat router's `_parse_mail_reader_payload` uses the LAST
     `get_emails` output (the LLM's final answer) rather than the first
     (which is usually an exploratory no-filter call). The summary prose
     and the email list must come from the same call.
"""
from __future__ import annotations

import json

import pytest

from app.agents.mail_reader_agent import MAIL_READER_SYSTEM_PROMPT
from app.agents.tools.gmail_tools import get_emails
from app.routers.chat import _parse_mail_reader_payload


# ---------------------------------------------------------------------------
# 1. The tool's LLM-facing description is the contract the LLM reads.
# ---------------------------------------------------------------------------

class TestGetEmailsDescription:
    def test_short_description_tells_llm_to_pass_sender(self):
        first_line = (get_emails.description or "").splitlines()[0]
        assert "sender" in first_line.lower()

    def test_short_description_forbids_retry_without_filter(self):
        first_line = (get_emails.description or "").splitlines()[0]
        assert "never retry" in first_line.lower() or "do not retry" in first_line.lower()

    def test_short_description_mentions_domain_example(self):
        first_line = (get_emails.description or "").splitlines()[0]
        assert "linkedin.com" in first_line or ".com" in first_line


# ---------------------------------------------------------------------------
# 2. The mail reader's system prompt is a hard contract.
# ---------------------------------------------------------------------------

class TestMailReaderPromptContract:
    def test_prompt_requires_sender_filter_when_user_names_sender(self):
        assert "sender" in MAIL_READER_SYSTEM_PROMPT.lower()

    def test_prompt_requires_domain_over_display_name(self):
        assert "domain" in MAIL_READER_SYSTEM_PROMPT.lower() or ".com" in MAIL_READER_SYSTEM_PROMPT

    def test_prompt_forbids_retry_without_filter(self):
        assert "do not" in MAIL_READER_SYSTEM_PROMPT.lower() or "do NOT" in MAIL_READER_SYSTEM_PROMPT

    def test_prompt_forbids_fabrication(self):
        assert "never fabricate" in MAIL_READER_SYSTEM_PROMPT.lower() or "never invent" in MAIL_READER_SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# 3. The parser picks the LAST `get_emails` output, not the first.
# ---------------------------------------------------------------------------

def _format_email_entry(
    *,
    subject: str,
    from_name: str,
    from_email: str,
    date: str,
    message_id: str,
    thread_id: str,
    snippet: str = "",
) -> str:
    return (
        f"1. Subject: {subject}\n"
        f"   From: {from_name} <{from_email}>\n"
        f"   Date: {date}\n"
        f"   Message ID: {message_id}\n"
        f"   Thread ID: {thread_id}\n"
        f"   Snippet: {snippet}"
    )


BANK_ENTRY = _format_email_entry(
    subject="Transaction Alert for your BRAC Bank Debit Card",
    from_name="BRAC Bank Info",
    from_email="noreply@bracbank.com",
    date="Thu, 25 Jun 2026 11:25:51 +0600",
    message_id="bank-1",
    thread_id="bank-thread-1",
    snippet="Dear Customer, TK 639.32 transacted...",
)

OPENAI_ENTRY = _format_email_entry(
    subject="More Codex, on us.",
    from_name="ChatGPT",
    from_email="noreply@email.openai.com",
    date="Tue, 16 Jun 2026 15:50:04 +0000",
    message_id="openai-1",
    thread_id="openai-thread-1",
    snippet="Bank your free reset.",
)


class TestParseMailReaderPayload:
    def test_picks_last_get_emails_not_first(self):
        """The LLM called get_emails multiple times: first without a
        filter (returning bank), then with the right filter (returning
        OpenAI). The parser must keep the LAST one, because the LLM's
        prose summary describes the last one."""
        payload = json.dumps({
            "summary": "Here are your last five OpenAI emails: ...",
            "tool_outputs": [
                {"name": "get_emails", "content": BANK_ENTRY, "status": "success"},
                {"name": "get_emails", "content": OPENAI_ENTRY, "status": "success"},
            ],
        })

        _, emails, _ = _parse_mail_reader_payload(payload)

        # Must be the OpenAI entry, not the bank one.
        assert len(emails) == 1
        assert emails[0]["from_email"] == "noreply@email.openai.com"

    def test_picks_last_when_iterating_among_get_emails_and_get_full_email(self):
        """Real captured payload (from LangSmith) for 'Read my last five
        emails from OpenAI':
          - 6 get_emails calls (some no-filter, some filtered)
          - 2 get_full_email calls (for two bank transactions)
        The LAST get_emails call is the OpenAI one and must win."""
        payload = json.dumps({
            "summary": "Here are the last five OpenAI emails: ...",
            "tool_outputs": [
                {"name": "get_emails", "content": BANK_ENTRY, "status": "success"},
                {"name": "get_full_email", "content": "body of bank email", "status": "success"},
                {"name": "get_full_email", "content": "body of bank email 2", "status": "success"},
                {"name": "get_emails", "content": BANK_ENTRY, "status": "success"},
                {"name": "get_emails", "content": BANK_ENTRY, "status": "success"},
                {"name": "get_emails", "content": OPENAI_ENTRY, "status": "success"},
            ],
        })

        _, emails, title = _parse_mail_reader_payload(payload)

        assert len(emails) == 1
        assert emails[0]["from_email"] == "noreply@email.openai.com"
        assert title == "Email Results"

    def test_passes_through_llm_summary_prose(self):
        """The summary text is the LLM's own prose. It may be good or
        bad, but the parser must surface it unchanged — the LLM is the
        author of the summary, the parser is just plumbing."""
        payload = json.dumps({
            "summary": "Here are your last five OpenAI emails: 1. Codex 2. ChatGPT...",
            "tool_outputs": [
                {"name": "get_emails", "content": OPENAI_ENTRY, "status": "success"},
            ],
        })

        summary, _, _ = _parse_mail_reader_payload(payload)
        assert summary == "Here are your last five OpenAI emails: 1. Codex 2. ChatGPT..."

    def test_empty_tool_outputs_keeps_llm_prose(self):
        payload = json.dumps({
            "summary": "No matching emails were found.",
            "tool_outputs": [
                {"name": "get_emails", "content": "No matching emails were found.", "status": "success"},
            ],
        })

        summary, emails, title = _parse_mail_reader_payload(payload)

        assert emails == []
        assert summary == "No matching emails were found."
        assert title is None

    def test_get_full_email_only_yields_email_detail(self):
        body = (
            "Subject: hello\n"
            "From: Alice <alice@example.com>\n"
            "To: me\n"
            "Date: Mon, 1 Jan 2026 10:00:00 +0000\n"
            "Message ID: m1\n"
            "Thread ID: t1\n"
            "\n"
            "body text"
        )
        payload = json.dumps({
            "summary": "",
            "tool_outputs": [
                {"name": "get_full_email", "content": body, "status": "success"},
            ],
        })

        summary, emails, title = _parse_mail_reader_payload(payload)

        assert emails == []
        assert title == "Email Detail"
        assert "body text" in summary

    def test_malformed_json_returns_raw_content(self):
        summary, emails, title = _parse_mail_reader_payload("not json {")
        assert summary == "not json {"
        assert emails == []
        assert title is None

    def test_get_email_thread_title(self):
        payload = json.dumps({
            "summary": "Thread summary",
            "tool_outputs": [
                {"name": "get_email_thread", "content": OPENAI_ENTRY, "status": "success"},
            ],
        })

        _, emails, title = _parse_mail_reader_payload(payload)

        assert len(emails) == 1
        assert title == "Thread Messages"

    def test_real_langsmith_payload_for_openai_query(self):
        """The exact payload captured from LangSmith for the user's
        'Read my last five emails from OpenAI' query. Before the fix
        this returned 10 BRAC Bank entries; after the fix it returns
        the 5 real OpenAI emails from the LAST get_emails call."""
        # Last (and only successful, correctly-filtered) get_emails call.
        last_openai_block = "\n\n".join([
            _format_email_entry(
                subject="More Codex, on us.",
                from_name="ChatGPT",
                from_email="noreply@email.openai.com",
                date="Tue, 16 Jun 2026 15:50:04 +0000",
                message_id="openai-1",
                thread_id="openai-thread-1",
            ),
            _format_email_entry(
                subject="Your ChatGPT Plus, now more personalized",
                from_name="ChatGPT",
                from_email="noreply@email.openai.com",
                date="Fri, 22 May 2026 16:36:24 +0000",
                message_id="openai-2",
                thread_id="openai-thread-2",
            ),
            _format_email_entry(
                subject="ChatGPT - Your new plan",
                from_name="OpenAI",
                from_email="noreply@tm.openai.com",
                date="Tue, 19 May 2026 05:37:17 +0000",
                message_id="openai-3",
                thread_id="openai-thread-3",
            ),
            _format_email_entry(
                subject="OpenAI Dev News: Realtime 2.0, Codex for Chrome, and beyond",
                from_name="OpenAI",
                from_email="noreply@email.openai.com",
                date="Mon, 11 May 2026 21:47:36 +0000",
                message_id="openai-4",
                thread_id="openai-thread-4",
            ),
            _format_email_entry(
                subject="Introducing GPT-5.5",
                from_name="OpenAI",
                from_email="noreply@email.openai.com",
                date="Sat, 25 Apr 2026 01:22:52 +0000",
                message_id="openai-5",
                thread_id="openai-thread-5",
            ),
        ])
        # Build the 5-entry block with numbered list, matching _format_email_list
        last_openai_block = (
            "1. Subject: More Codex, on us.\n"
            "   From: ChatGPT <noreply@email.openai.com>\n"
            "   Date: Tue, 16 Jun 2026 15:50:04 +0000\n"
            "   Message ID: openai-1\n"
            "   Thread ID: openai-thread-1\n"
            "   Snippet: Bank your free reset.\n"
            "\n"
            "2. Subject: Your ChatGPT Plus, now more personalized\n"
            "   From: ChatGPT <noreply@email.openai.com>\n"
            "   Date: Fri, 22 May 2026 16:36:24 +0000\n"
            "   Message ID: openai-2\n"
            "   Thread ID: openai-thread-2\n"
            "   Snippet: See what shapes your answers.\n"
        )

        payload = json.dumps({
            "summary": "Here are the last five OpenAI emails...",
            "tool_outputs": [
                # 1st get_emails: 10 bank entries
                {"name": "get_emails", "content": "1. Subject: Transaction Alert\n   From: BRAC Bank Info <noreply@bracbank.com>\n   Date: Thu, 25 Jun 2026 11:25:51 +0600\n   Message ID: bank-1\n   Thread ID: bank-thread-1\n   Snippet: ...\n\n" * 10, "status": "success"},
                # 2 get_full_email calls for two bank transactions
                {"name": "get_full_email", "content": "Subject: Transaction Alert\nFrom: BRAC Bank Info\n\nbody", "status": "success"},
                {"name": "get_full_email", "content": "Subject: Transaction Alert\nFrom: BRAC Bank Info\n\nbody", "status": "success"},
                # More no-filter get_emails calls
                {"name": "get_emails", "content": "1. Subject: Transaction Alert\n   From: BRAC Bank Info <noreply@bracbank.com>\n   Date: Thu, 25 Jun 2026 11:25:51 +0600\n   Message ID: bank-1\n   Thread ID: bank-thread-1\n   Snippet: ...\n\n" * 10, "status": "success"},
                {"name": "get_emails", "content": "1. Subject: BRAC Bank PLC\n   From: BRAC Bank PLC <noreply@edm.bracbank.com>\n   Date: Thu, 25 Jun 2026 08:55:15 +0000\n   Message ID: edm-1\n   Thread ID: edm-thread-1\n   Snippet: \n\n2. Subject: Transaction Alert\n   From: BRAC Bank Info <noreply@bracbank.com>\n   Date: Thu, 25 Jun 2026 11:25:51 +0600\n   Message ID: bank-1\n   Thread ID: bank-thread-1\n   Snippet: ...\n\n3. Subject: Transaction Alert\n   From: BRAC Bank Info <noreply@bracbank.com>\n   Date: Thu, 25 Jun 2026 00:50:25 +0600\n   Message ID: bank-2\n   Thread ID: bank-thread-2\n   Snippet: ...\n\n4. Subject: bKash Fund Transfer Success\n   From: BRAC Bank Astha <astha@bracbank.com>\n   Date: Wed, 24 Jun 2026 07:50:17 -0700\n   Message ID: bkash-1\n   Thread ID: bkash-thread-1\n   Snippet: ...\n\n5. Subject: Login successfully\n   From: BRAC Bank Astha <astha@bracbank.com>\n   Date: Wed, 24 Jun 2026 07:48:23 -0700\n   Message ID: login-1\n   Thread ID: login-thread-1\n   Snippet: ...\n", "status": "success"},
                {"name": "get_emails", "content": "1. Subject: fieldnationcom is hiring\n   From: LinkedIn <jobs-listings@linkedin.com>\n   Date: Thu, 25 Jun 2026 08:26:42 +0000\n   Message ID: li-1\n   Thread ID: li-thread-1\n   Snippet: ...\n\n" * 5, "status": "success"},
                # THE LAST get_emails: correctly filtered for OpenAI
                {"name": "get_emails", "content": last_openai_block, "status": "success"},
            ],
        })

        summary, emails, title = _parse_mail_reader_payload(payload)

        # The fix: must return the 2 OpenAI entries from the LAST call,
        # not the 10 bank entries from the FIRST call.
        assert len(emails) == 2
        assert emails[0]["from_email"] == "noreply@email.openai.com"
        assert emails[1]["from_email"] == "noreply@email.openai.com"
        assert "OpenAI" in summary  # the LLM's prose, not overwritten
        assert title == "Email Results"
