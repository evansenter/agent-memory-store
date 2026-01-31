"""Tests for the CLI."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database path."""
    return str(tmp_path / "test_memories.db")


def run_cli(*args, db_path: str) -> subprocess.CompletedProcess:
    """Run the CLI with given arguments."""
    cmd = [
        sys.executable,
        "-m",
        "agent_memory_store.cli",
        "--db",
        db_path,
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


class TestStore:
    """Tests for the store command."""

    def test_store_basic(self, temp_db):
        """Test storing a basic memory."""
        result = run_cli("store", "test-key", "test value", db_path=temp_db)
        assert result.returncode == 0
        assert "Stored: test-key" in result.stdout

    def test_store_with_namespace(self, temp_db):
        """Test storing with namespace."""
        result = run_cli(
            "store",
            "test-key",
            "test value",
            "--namespace",
            "project:test",
            db_path=temp_db,
        )
        assert result.returncode == 0
        assert "Stored: test-key" in result.stdout

    def test_store_with_tags(self, temp_db):
        """Test storing with tags."""
        result = run_cli(
            "store",
            "test-key",
            "test value",
            "--tags",
            "foo,bar,baz",
            db_path=temp_db,
        )
        assert result.returncode == 0

    def test_store_with_ttl(self, temp_db):
        """Test storing with TTL."""
        result = run_cli(
            "store", "test-key", "test value", "--ttl", "7", db_path=temp_db
        )
        assert result.returncode == 0

    def test_store_unicode(self, temp_db):
        """Test storing unicode values."""
        result = run_cli(
            "store", "unicode-key", "Hello 世界! 🌍", db_path=temp_db
        )
        assert result.returncode == 0

    def test_store_update(self, temp_db):
        """Test updating an existing key."""
        run_cli("store", "test-key", "original", db_path=temp_db)
        run_cli("store", "test-key", "updated", db_path=temp_db)

        result = run_cli("recall", "test-key", db_path=temp_db)
        assert "updated" in result.stdout


class TestRecall:
    """Tests for the recall command."""

    def test_recall_by_key(self, temp_db):
        """Test recalling by exact key."""
        run_cli("store", "my-key", "my value", db_path=temp_db)

        result = run_cli("recall", "my-key", db_path=temp_db)
        assert result.returncode == 0
        assert "my value" in result.stdout

    def test_recall_not_found(self, temp_db):
        """Test recalling non-existent key."""
        result = run_cli("recall", "nonexistent", db_path=temp_db)
        assert result.returncode == 1
        assert "not found" in result.stdout.lower() or "not found" in result.stderr.lower()

    def test_recall_search(self, temp_db):
        """Test search recall."""
        run_cli("store", "searchable", "find me please", db_path=temp_db)

        result = run_cli("recall", "-s", "find", db_path=temp_db)
        assert result.returncode == 0
        assert "find me please" in result.stdout

    def test_recall_search_no_results(self, temp_db):
        """Test search with no results."""
        run_cli("store", "something", "value", db_path=temp_db)

        result = run_cli("recall", "-s", "nonexistent-xyz", db_path=temp_db)
        # Should not crash (was a bug with hyphens). Message goes to stderr.
        assert "No memories found" in result.stderr or "No memories found" in result.stdout


class TestForget:
    """Tests for the forget command."""

    def test_forget_existing(self, temp_db):
        """Test forgetting an existing memory."""
        run_cli("store", "to-forget", "value", db_path=temp_db)

        result = run_cli("forget", "to-forget", "-f", db_path=temp_db)
        assert result.returncode == 0
        assert "Forgot" in result.stdout

        # Verify it's gone
        result = run_cli("recall", "to-forget", db_path=temp_db)
        assert "not found" in result.stdout.lower() or result.returncode == 1

    def test_forget_nonexistent(self, temp_db):
        """Test forgetting non-existent memory."""
        result = run_cli("forget", "nonexistent", "-f", db_path=temp_db)
        output = (result.stdout + result.stderr).lower()
        assert "not found" in output


class TestList:
    """Tests for the list command."""

    def test_list_empty(self, temp_db):
        """Test listing with no memories."""
        result = run_cli("list", db_path=temp_db)
        assert "No memories" in result.stdout

    def test_list_all(self, temp_db):
        """Test listing all memories."""
        run_cli("store", "key1", "value1", db_path=temp_db)
        run_cli("store", "key2", "value2", db_path=temp_db)

        result = run_cli("list", db_path=temp_db)
        assert result.returncode == 0
        assert "key1" in result.stdout
        assert "key2" in result.stdout

    def test_list_json(self, temp_db):
        """Test JSON output."""
        run_cli("store", "key1", "value1", db_path=temp_db)

        result = run_cli("list", "--json", db_path=temp_db)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert data[0]["key"] == "key1"

    def test_list_with_namespace_filter(self, temp_db):
        """Test filtering by namespace."""
        run_cli("store", "key1", "value1", "--namespace", "ns1", db_path=temp_db)
        run_cli("store", "key2", "value2", "--namespace", "ns2", db_path=temp_db)

        result = run_cli("list", "--namespace", "ns1", db_path=temp_db)
        assert "key1" in result.stdout
        assert "key2" not in result.stdout

    def test_list_with_tags_filter(self, temp_db):
        """Test filtering by tags."""
        run_cli("store", "key1", "value1", "--tags", "foo", db_path=temp_db)
        run_cli("store", "key2", "value2", "--tags", "bar", db_path=temp_db)

        result = run_cli("list", "--tags", "foo", db_path=temp_db)
        assert "key1" in result.stdout
        assert "key2" not in result.stdout


class TestEdgeCases:
    """Test edge cases and potential issues."""

    def test_special_characters_in_key(self, temp_db):
        """Test keys with special characters."""
        result = run_cli("store", "path/to/resource", "value", db_path=temp_db)
        assert result.returncode == 0

        result = run_cli("recall", "path/to/resource", db_path=temp_db)
        assert "value" in result.stdout

    def test_json_value(self, temp_db):
        """Test JSON as value."""
        json_val = '{"key": "value", "nested": {"a": 1}}'
        result = run_cli("store", "json-key", json_val, db_path=temp_db)
        assert result.returncode == 0

        result = run_cli("recall", "json-key", db_path=temp_db)
        assert "nested" in result.stdout

    def test_empty_value(self, temp_db):
        """Test empty value."""
        result = run_cli("store", "empty-key", "", db_path=temp_db)
        assert result.returncode == 0

    def test_hyphenated_search(self, temp_db):
        """Test search with hyphens (was a bug)."""
        run_cli("store", "test", "some value", db_path=temp_db)

        # This used to crash with "no such column". Now gracefully returns no results.
        result = run_cli("recall", "-s", "non-existent-term", db_path=temp_db)
        output = result.stdout + result.stderr
        # Either succeeds with empty or shows "No memories found"
        assert "No memories" in output or result.returncode == 0
