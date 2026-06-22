from __future__ import annotations

import asyncio
import importlib
import sys
from unittest import TestCase


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
