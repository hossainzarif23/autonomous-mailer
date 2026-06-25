from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest_plugins: list[str] = []

# Make `backend/` importable when pytest is invoked from the repo root.
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
