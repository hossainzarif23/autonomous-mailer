from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from app.agents import coordinator, mail_reader_agent


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
