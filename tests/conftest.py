"""Pytest fixtures for agent-memory-store tests."""

import tempfile
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
