from __future__ import annotations

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from app.agents import coordinator, mail_reader_agent, mailing_agent


class AgentFactoryTests(TestCase):
    def test_mail_reader_agent_factory_uses_create_agent(self):
        mail_reader_agent._mail_reader_agent = None
        mail_reader_agent._mail_reader_checkpointer_id = None

        with patch("app.agents.mail_reader_agent.create_agent", return_value="mail-reader") as create_agent_mock:
            with patch("app.agents.mail_reader_agent.get_llm", return_value="llm"):
                agent = mail_reader_agent.get_mail_reader_agent()

        self.assertEqual(agent, "mail-reader")
        self.assertTrue(create_agent_mock.called)

    def test_coordinator_factory_uses_create_agent(self):
        coordinator._coordinator_agent = None
        coordinator._coordinator_checkpointer_id = None

        with patch("app.agents.coordinator.create_agent", return_value="coordinator-agent") as create_agent_mock:
            with patch("app.agents.coordinator.get_llm", return_value="llm"):
                with patch("app.agents.coordinator.make_coordinator_tools", return_value=["tool-a", "tool-b"]):
                    agent = coordinator.get_coordinator_agent(checkpointer=None)

        self.assertEqual(agent, "coordinator-agent")
        self.assertTrue(create_agent_mock.called)

    def test_mailing_draft_agent_factory_uses_create_agent(self):
        mailing_agent._mailing_draft_agent = None
        mailing_agent._mailing_draft_checkpointer_id = None

        with patch("app.agents.mailing_agent.create_agent", return_value="mailing-draft-agent") as create_agent_mock:
            with patch("app.agents.mailing_agent.get_llm", return_value="llm"):
                agent = mailing_agent.get_mailing_draft_agent()

        self.assertEqual(agent, "mailing-draft-agent")
        self.assertTrue(create_agent_mock.called)


class AgentMiddlewareTests(IsolatedAsyncioTestCase):
    async def test_fresh_email_routing_short_circuits_to_coordinator_tool_call(self):
        request = SimpleNamespace(
            messages=[
                HumanMessage(
                    content="Write a fresh email to ceo@example.com about AI trends in Bangladesh."
                )
            ]
        )

        handler_called = False

        async def handler(_request):
            nonlocal handler_called
            handler_called = True
            return None

        response = await coordinator.fresh_email_routing.awrap_model_call(request, handler)

        self.assertFalse(handler_called)
        self.assertIsInstance(response, AIMessage)
        self.assertEqual(response.tool_calls[0]["name"], "prepare_fresh_email_with_research")
