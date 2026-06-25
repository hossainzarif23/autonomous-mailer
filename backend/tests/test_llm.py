from __future__ import annotations

from unittest.mock import patch

from app.agents.llm import get_llm


def test_get_llm_returns_chat_model_instance():
    get_llm.cache_clear()
    expected_model = object()

    with patch("app.agents.llm.ChatGoogleGenerativeAI", return_value=expected_model):
        assert get_llm() is expected_model

    get_llm.cache_clear()
