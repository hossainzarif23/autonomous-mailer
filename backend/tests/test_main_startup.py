from __future__ import annotations

import asyncio
import importlib
import sys
from unittest import TestCase
from unittest.mock import patch


class StartupEventLoopTests(TestCase):
    def test_uvicorn_selector_loop_factory_returns_selector_loop_on_windows(self):
        if sys.platform != "win32":
            self.skipTest("Windows-only startup guard")

        from app.uvicorn_loop import selector_loop_factory

        loop = selector_loop_factory()
        try:
            self.assertIsInstance(loop, asyncio.SelectorEventLoop)
        finally:
            loop.close()

    def test_main_import_configures_windows_selector_event_loop_policy(self):
        if sys.platform != "win32":
            self.skipTest("Windows-only startup guard")

        import app.main

        importlib.reload(app.main)

        self.assertIsInstance(
            asyncio.get_event_loop_policy(),
            asyncio.WindowsSelectorEventLoopPolicy,
        )

    def test_dev_server_runs_uvicorn_with_selector_loop(self):
        from app import dev_server

        with patch.dict("os.environ", {}, clear=True), patch("uvicorn.run") as run:
            dev_server.main()

        run.assert_called_once_with(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            loop="app.uvicorn_loop:selector_loop_factory",
        )

    def test_dev_server_uses_api_port_env_override(self):
        from app import dev_server

        with patch.dict("os.environ", {"API_PORT": "8042"}, clear=True), patch(
            "uvicorn.run"
        ) as run:
            dev_server.main()

        self.assertEqual(run.call_args.kwargs["port"], 8042)
