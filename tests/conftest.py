"""Pytest fixtures for agent-memory-store tests."""

import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_memory_store.storage import MemoryStorage


@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield Path(f.name)
        # Cleanup
        Path(f.name).unlink(missing_ok=True)


@pytest.fixture
def storage(temp_db):
    """Create a MemoryStorage instance with a temp database."""
    return MemoryStorage(temp_db)


@pytest.fixture
def expire_memory(temp_db):
    """Manually expire a memory by setting expires_at to the past."""

    def _expire(key: str):
        with sqlite3.connect(temp_db) as conn:
            past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
            conn.execute("UPDATE memories SET expires_at = ? WHERE key = ?", (past, key))

    return _expire
