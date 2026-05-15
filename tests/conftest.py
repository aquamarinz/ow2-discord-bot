"""Pytest fixtures for ow_bot tests."""
from __future__ import annotations
import os
import sys

# Make bot modules importable from tests (bot files live at repo root,
# not under a src/ subdir; tests/ is sibling of those modules)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest_asyncio


@pytest_asyncio.fixture
async def tmp_db(tmp_path, monkeypatch):
    """A clean Database instance pointing at a tmp_path SQLite file."""
    from database import Database
    import config

    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "test.db"))
    db = Database()
    await db.initialize()
    yield db
    await db.close()
