from datetime import UTC, datetime, timedelta
"""Unit tests for storage.py - CRUD, FTS5, and TTL functionality."""

import json
import sqlite3
from datetime import datetime, timedelta

from agent_memory_store.storage import Memory, MemoryStorage


class TestMemoryDataclass:
    """Tests for the Memory dataclass."""

    def test_memory_creation(self):
        """Test creating a Memory instance."""
        now = datetime.now(UTC)
        memory = Memory(
            id="test-id",
            key="test-key",
            value="test-value",
            namespace="global",
            tags=["tag1", "tag2"],
            created_at=now,
            updated_at=now,
        )
        assert memory.id == "test-id"
        assert memory.key == "test-key"
        assert memory.value == "test-value"
        assert memory.namespace == "global"
        assert memory.tags == ["tag1", "tag2"]
        assert memory.created_by is None
        assert memory.expires_at is None
        assert memory.access_count == 0
        assert memory.last_accessed_at is None

    def test_memory_with_optional_fields(self):
        """Test Memory with all optional fields."""
        now = datetime.now(UTC)
        expires = now + timedelta(days=7)
        memory = Memory(
            id="test-id",
            key="test-key",
            value="test-value",
            namespace="project:test",
            tags=["important"],
            created_at=now,
            updated_at=now,
            created_by="agent-1",
            expires_at=expires,
            access_count=5,
            last_accessed_at=now,
        )
        assert memory.created_by == "agent-1"
        assert memory.expires_at == expires
        assert memory.access_count == 5
        assert memory.last_accessed_at == now


class TestMemoryStorageInit:
    """Tests for MemoryStorage initialization."""

    def test_creates_database_file(self, temp_db):
        """Test that initializing storage creates the database file."""
        storage = MemoryStorage(temp_db)
        assert temp_db.exists()

    def test_creates_tables(self, storage, temp_db):
        """Test that required tables are created."""
        with sqlite3.connect(temp_db) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in cursor.fetchall()}

        assert "memories" in tables
        assert "memories_fts" in tables

    def test_creates_indexes(self, storage, temp_db):
        """Test that required indexes are created."""
        with sqlite3.connect(temp_db) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
            indexes = {row[0] for row in cursor.fetchall()}

        assert "idx_memories_namespace" in indexes
        assert "idx_memories_expires" in indexes

    def test_creates_fts_triggers(self, storage, temp_db):
        """Test that FTS sync triggers are created."""
        with sqlite3.connect(temp_db) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
            triggers = {row[0] for row in cursor.fetchall()}

        assert "memories_ai" in triggers  # After insert
        assert "memories_ad" in triggers  # After delete
        assert "memories_au" in triggers  # After update


class TestCRUDOperations:
    """Tests for Create, Read, Update, Delete operations."""

    def test_store_new_memory(self, storage):
        """Test storing a new memory."""
        memory = storage.store(key="greeting", value="Hello, world!")

        assert memory.key == "greeting"
        assert memory.value == "Hello, world!"
        assert memory.namespace == "global"
        assert memory.tags == []
        assert memory.id is not None
        assert memory.created_at is not None
        assert memory.updated_at is not None

    def test_store_with_namespace(self, storage):
        """Test storing with a custom namespace."""
        memory = storage.store(
            key="config", value="debug=true", namespace="project:myapp"
        )
        assert memory.namespace == "project:myapp"

    def test_store_with_tags(self, storage):
        """Test storing with tags."""
        memory = storage.store(
            key="note", value="Important note", tags=["important", "todo"]
        )
        assert memory.tags == ["important", "todo"]

    def test_store_with_created_by(self, storage):
        """Test storing with created_by field."""
        memory = storage.store(
            key="agent-note", value="Agent observation", created_by="claude-1"
        )
        assert memory.created_by == "claude-1"

    def test_store_update_existing(self, storage):
        """Test that storing with existing key updates the memory."""
        storage.store(key="counter", value="1")
        updated = storage.store(key="counter", value="2")

        assert updated.value == "2"

        # Verify only one record exists
        recalled = storage.recall_by_key("counter")
        assert recalled.value == "2"

    def test_recall_by_key_exists(self, storage):
        """Test recalling an existing memory."""
        storage.store(key="secret", value="password123")
        memory = storage.recall_by_key("secret")

        assert memory is not None
        assert memory.key == "secret"
        assert memory.value == "password123"

    def test_recall_by_key_not_found(self, storage):
        """Test recalling a non-existent memory."""
        memory = storage.recall_by_key("nonexistent")
        assert memory is None

    def test_recall_updates_access_stats(self, storage):
        """Test that recall updates access_count and last_accessed_at."""
        storage.store(key="tracked", value="data")

        # First recall
        memory1 = storage.recall_by_key("tracked")
        assert memory1.access_count == 0  # Original row data before update

        # Second recall should show updated stats
        memory2 = storage.recall_by_key("tracked")
        assert memory2.access_count == 1
        assert memory2.last_accessed_at is not None

    def test_forget_existing(self, storage):
        """Test deleting an existing memory."""
        storage.store(key="temporary", value="delete me")
        result = storage.forget("temporary")

        assert result is True
        assert storage.recall_by_key("temporary") is None

    def test_forget_nonexistent(self, storage):
        """Test deleting a non-existent memory."""
        result = storage.forget("nonexistent")
        assert result is False


class TestFTS5Search:
    """Tests for FTS5 full-text search functionality."""

    def test_search_by_value(self, storage):
        """Test searching by value content."""
        storage.store(key="doc1", value="The quick brown fox jumps")
        storage.store(key="doc2", value="The lazy dog sleeps")
        storage.store(key="doc3", value="A fox is cunning")

        results = storage.search("fox")
        keys = {m.key for m in results}

        assert "doc1" in keys
        assert "doc3" in keys
        assert "doc2" not in keys

    def test_search_by_key(self, storage):
        """Test searching by key content."""
        storage.store(key="python-basics", value="Learn Python")
        storage.store(key="rust-basics", value="Learn Rust")

        results = storage.search("python")
        assert len(results) == 1
        assert results[0].key == "python-basics"

    def test_search_by_tags(self, storage):
        """Test searching finds content in tags."""
        storage.store(key="task1", value="Do laundry", tags=["chore", "home"])
        storage.store(key="task2", value="Write code", tags=["work", "coding"])

        results = storage.search("chore")
        assert len(results) == 1
        assert results[0].key == "task1"

    def test_search_with_namespace_filter(self, storage):
        """Test filtering search results by namespace."""
        storage.store(key="global1", value="Test data", namespace="global")
        storage.store(key="project1", value="Test data", namespace="project:app")

        results = storage.search("test", namespace="project:app")
        assert len(results) == 1
        assert results[0].key == "project1"

    def test_search_with_tags_filter(self, storage):
        """Test filtering search results by tags."""
        storage.store(key="note1", value="Remember this", tags=["important"])
        storage.store(key="note2", value="Remember that", tags=["trivial"])

        results = storage.search("remember", tags=["important"])
        assert len(results) == 1
        assert results[0].key == "note1"

    def test_search_limit(self, storage):
        """Test search respects limit parameter."""
        for i in range(10):
            storage.store(key=f"item{i}", value="searchable content")

        results = storage.search("searchable", limit=3)
        assert len(results) == 3

    def test_search_no_results(self, storage):
        """Test search returns empty list when no matches."""
        storage.store(key="doc", value="Hello world")
        results = storage.search("nonexistent")
        assert results == []

    def test_fts_sync_on_update(self, storage):
        """Test FTS index is updated when memory is updated."""
        storage.store(key="changeable", value="original content")
        storage.store(key="changeable", value="updated content new")

        # Should find with new content
        results = storage.search("updated")
        assert len(results) == 1

        # Should NOT find with old content (depending on FTS behavior)
        # Actually FTS might still match "content" - let's search for something unique
        results = storage.search("original")
        assert len(results) == 0

    def test_fts_sync_on_delete(self, storage):
        """Test FTS index is updated when memory is deleted."""
        storage.store(key="deletable", value="unique searchterm xyz")
        storage.forget("deletable")

        results = storage.search("searchterm")
        assert len(results) == 0


class TestTTL:
    """Tests for TTL (Time-To-Live) functionality."""

    def test_store_with_ttl(self, storage):
        """Test storing a memory with TTL."""
        memory = storage.store(key="ephemeral", value="temporary", ttl_days=7)

        assert memory.expires_at is not None
        expected_expiry = datetime.now(UTC) + timedelta(days=7)
        # Allow 1 second tolerance
        assert abs((memory.expires_at - expected_expiry).total_seconds()) < 1

    def test_store_without_ttl(self, storage):
        """Test that memories without TTL have no expiration."""
        memory = storage.store(key="permanent", value="forever")
        assert memory.expires_at is None

    def test_ttl_stored_in_database(self, storage, temp_db):
        """Test that TTL is persisted in the database."""
        storage.store(key="timed", value="data", ttl_days=30)

        with sqlite3.connect(temp_db) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT expires_at FROM memories WHERE key = ?", ("timed",)
            )
            row = cursor.fetchone()

        assert row["expires_at"] is not None
        expires = datetime.fromisoformat(row["expires_at"])
        expected = datetime.now(UTC) + timedelta(days=30)
        assert abs((expires - expected).total_seconds()) < 1

    def test_ttl_update_on_re_store(self, storage):
        """Test that TTL is updated when memory is re-stored."""
        storage.store(key="refresh", value="v1", ttl_days=7)
        updated = storage.store(key="refresh", value="v2", ttl_days=30)

        expected = datetime.now(UTC) + timedelta(days=30)
        assert abs((updated.expires_at - expected).total_seconds()) < 1


class TestListMemories:
    """Tests for list_memories functionality."""

    def test_list_all(self, storage):
        """Test listing all memories."""
        storage.store(key="a", value="1")
        storage.store(key="b", value="2")
        storage.store(key="c", value="3")

        memories = storage.list_memories()
        assert len(memories) == 3

    def test_list_with_namespace_filter(self, storage):
        """Test filtering by namespace."""
        storage.store(key="g1", value="1", namespace="global")
        storage.store(key="p1", value="2", namespace="project:x")
        storage.store(key="p2", value="3", namespace="project:x")

        memories = storage.list_memories(namespace="project:x")
        assert len(memories) == 2
        assert all(m.namespace == "project:x" for m in memories)

    def test_list_with_tags_filter(self, storage):
        """Test filtering by tags."""
        storage.store(key="t1", value="1", tags=["urgent"])
        storage.store(key="t2", value="2", tags=["normal"])
        storage.store(key="t3", value="3", tags=["urgent", "important"])

        memories = storage.list_memories(tags=["urgent"])
        assert len(memories) == 2
        keys = {m.key for m in memories}
        assert keys == {"t1", "t3"}

    def test_list_with_since_filter(self, storage, temp_db):
        """Test filtering by creation date."""
        # Store a memory
        storage.store(key="recent", value="new")

        # Manually insert an old memory
        with sqlite3.connect(temp_db) as conn:
            old_date = (datetime.now(UTC) - timedelta(days=10)).isoformat()
            conn.execute(
                """
                INSERT INTO memories (id, key, value, namespace, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("old-id", "old", "ancient", "global", "[]", old_date, old_date),
            )

        # Filter to last 5 days
        since = datetime.now(UTC) - timedelta(days=5)
        memories = storage.list_memories(since=since)

        assert len(memories) == 1
        assert memories[0].key == "recent"

    def test_list_with_limit(self, storage):
        """Test limit parameter."""
        for i in range(10):
            storage.store(key=f"item{i}", value=str(i))

        memories = storage.list_memories(limit=5)
        assert len(memories) == 5

    def test_list_ordered_by_updated_at(self, storage):
        """Test that results are ordered by updated_at descending."""
        storage.store(key="first", value="1")
        storage.store(key="second", value="2")
        storage.store(key="third", value="3")

        memories = storage.list_memories()
        # Most recent first
        assert memories[0].key == "third"
        assert memories[2].key == "first"

    def test_list_empty(self, storage):
        """Test listing with no memories."""
        memories = storage.list_memories()
        assert memories == []


class TestRowToMemory:
    """Tests for _row_to_memory conversion."""

    def test_converts_all_fields(self, storage):
        """Test that all fields are properly converted."""
        storage.store(
            key="full",
            value="complete data",
            namespace="test",
            tags=["a", "b"],
            created_by="tester",
            ttl_days=5,
        )

        memory = storage.recall_by_key("full")

        assert isinstance(memory.id, str)
        assert isinstance(memory.key, str)
        assert isinstance(memory.value, str)
        assert isinstance(memory.namespace, str)
        assert isinstance(memory.tags, list)
        assert isinstance(memory.created_at, datetime)
        assert isinstance(memory.updated_at, datetime)
        assert memory.created_by == "tester"
        assert isinstance(memory.expires_at, datetime)
        assert isinstance(memory.access_count, int)

    def test_handles_null_optional_fields(self, storage):
        """Test handling of NULL optional fields."""
        storage.store(key="minimal", value="data")
        memory = storage.recall_by_key("minimal")

        assert memory.created_by is None
        assert memory.expires_at is None
        # last_accessed_at will be set on first recall
        # but initial store has it as NULL


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_unicode_content(self, storage):
        """Test handling of unicode characters."""
        memory = storage.store(
            key="unicode",
            value="Hello 世界 🌍 café",
            tags=["日本語", "emoji"],
        )

        recalled = storage.recall_by_key("unicode")
        assert recalled.value == "Hello 世界 🌍 café"
        assert "日本語" in recalled.tags

    def test_large_value(self, storage):
        """Test handling of large values."""
        large_text = "x" * 100000
        memory = storage.store(key="large", value=large_text)

        recalled = storage.recall_by_key("large")
        assert len(recalled.value) == 100000

    def test_special_characters_in_key(self, storage):
        """Test keys with special characters."""
        memory = storage.store(key="path/to/resource", value="data")
        recalled = storage.recall_by_key("path/to/resource")
        assert recalled is not None

    def test_empty_tags_list(self, storage):
        """Test storing with explicit empty tags."""
        memory = storage.store(key="no-tags", value="data", tags=[])
        assert memory.tags == []

    def test_json_in_value(self, storage):
        """Test storing JSON data as value."""
        data = {"nested": {"key": "value"}, "list": [1, 2, 3]}
        memory = storage.store(key="json-data", value=json.dumps(data))

        recalled = storage.recall_by_key("json-data")
        parsed = json.loads(recalled.value)
        assert parsed == data
