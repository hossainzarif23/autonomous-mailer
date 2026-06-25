from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agents import coordinator, mail_reader_agent, mailing_agent


@pytest.fixture(autouse=True)
def _reset_agent_cache():
    """Each test rebuilds the agent; clear the module-level cache first."""
    coordinator._coordinator_agent = None
    coordinator._coordinator_checkpointer_id = None
    mail_reader_agent._mail_reader_agent = None
    mail_reader_agent._mail_reader_checkpointer_id = None
    mailing_agent._mailing_agent = None
    mailing_agent._mailing_checkpointer_id = None
    yield


def test_mail_reader_agent_factory_uses_create_agent():
    with (
        patch("app.agents.mail_reader_agent.create_agent", return_value="mail-reader") as create_agent_mock,
        patch("app.agents.mail_reader_agent.get_llm", return_value="llm"),
    ):
        agent = mail_reader_agent.get_mail_reader_agent()

    assert agent == "mail-reader"
    assert create_agent_mock.called


def test_mailing_agent_factory_uses_create_agent():
    with (
        patch("app.agents.mailing_agent.create_agent", return_value="mailing-agent") as create_agent_mock,
        patch("app.agents.mailing_agent.get_llm", return_value="llm"),
    ):
        agent = mailing_agent.get_mailing_agent()

    assert agent == "mailing-agent"
    assert create_agent_mock.called


def test_coordinator_factory_uses_create_agent_without_dynamic_prompt():
    import types

    with (
        patch("app.agents.coordinator.create_agent", return_value="coordinator-agent") as create_agent_mock,
        patch("app.agents.coordinator.get_llm", return_value="llm"),
        patch("app.agents.coordinator.make_coordinator_tools", return_value=["tool-a", "tool-b"]),
    ):
        agent = coordinator.get_coordinator_agent(checkpointer=None)

    assert agent == "coordinator-agent"
    assert create_agent_mock.called
    # The cleanup pass removed the @dynamic_prompt middleware. The only
    # remaining middleware must be the HITL one — a class instance, not a
    # plain function.
    middleware = create_agent_mock.call_args.kwargs["middleware"]
    assert len(middleware) == 1
    assert not isinstance(middleware[0], types.FunctionType)


def test_coordinator_state_schema_drops_needs_research_refresh():
    assert hasattr(coordinator.EmailAgentState, "current_draft")
    assert hasattr(coordinator.EmailAgentState, "research_summary")
    assert hasattr(coordinator.EmailAgentState, "draft_feedback")
    assert not hasattr(coordinator.EmailAgentState, "needs_research_refresh")
