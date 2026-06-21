from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from app.agents.llm import get_llm


class LlmFactoryTests(TestCase):
    def test_get_llm_returns_chat_model_instance(self):
        get_llm.cache_clear()
        expected_model = object()

        with patch("app.agents.llm.ChatGoogleGenerativeAI", return_value=expected_model):
            self.assertIs(get_llm(), expected_model)

        get_llm.cache_clear()
