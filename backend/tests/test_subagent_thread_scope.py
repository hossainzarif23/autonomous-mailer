"""
Regression test: sub-agent state leak across conversations.

The mail reader / web search / mailing sub-agents are invoked with a
thread_id of `mail_reader_{user_id}`. That thread's state is persisted
in the global LangGraph checkpointer. So when the SAME user runs a new
conversation, the sub-agent's checkpoint still contains the OLD
ToolMessages from the previous conversation. Those stale ToolMessages
leak into the new conversation's `call_mail_reader` tool_outputs,
which then pollute the rendered email list.

The fix: scope sub-agent thread_ids by (user_id, conversation_id) so
state is fresh per conversation.
"""
from __future__ import annotations

import inspect

import pytest

from app.routers.chat import stream_chat_message


# ---------------------------------------------------------------------------
# The check: the mail reader's thread_id must include conversation_id.
# Read the source of the coordinator's tool wrappers and assert.
# ---------------------------------------------------------------------------

class TestSubAgentThreadScoping:
    """The coordinator's call_mail_reader tool uses
    `mail_reader_{user_id}` as the sub-agent's thread_id. That thread's
    state persists across conversations, which leaks old ToolMessages
    into new conversations.

    The fix: include conversation_id in the thread_id."""

    @pytest.fixture
    def coordinator_source(self) -> str:
        return inspect.getsource(
            __import__("app.agents.coordinator", fromlist=["make_coordinator_tools"]).make_coordinator_tools
        )

    def test_mail_reader_thread_id_includes_conversation_id(self, coordinator_source: str):
        # The leaky version is `f"mail_reader_{runtime.context.user_id}"`.
        # The fix is to include `runtime.context.conversation_id` so each
        # conversation has fresh sub-agent state.
        assert (
            "mail_reader_{runtime.context.conversation_id}" in coordinator_source
            or "mail_reader_{runtime.context.user_id}_{runtime.context.conversation_id}" in coordinator_source
        ), (
            "sub-agent thread_id must be conversation-scoped to prevent "
            "state leaking across conversations of the same user. "
            f"current source:\n{coordinator_source}"
        )

    def test_web_search_thread_id_includes_conversation_id(self, coordinator_source: str):
        assert (
            "search_{runtime.context.conversation_id}" in coordinator_source
            or "search_{runtime.context.user_id}_{runtime.context.conversation_id}" in coordinator_source
        ), "web search sub-agent thread_id must be conversation-scoped"

    def test_mailing_agent_thread_id_includes_conversation_id(self, coordinator_source: str):
        assert (
            "mailing_{runtime.context.conversation_id}" in coordinator_source
            or "mailing_{runtime.context.user_id}_{runtime.context.conversation_id}" in coordinator_source
        ), "mailing agent sub-agent thread_id must be conversation-scoped"
