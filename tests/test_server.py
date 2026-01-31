"""Integration tests for MCP server tools."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# We need to patch the DB_PATH before importing the server module
@pytest.fixture
def temp_db_path():
    """Create a temporary database path."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield f.name
        Path(f.name).unlink(missing_ok=True)


@pytest.fixture
def server_module(temp_db_path):
    """Import server module with patched database path."""
    with patch.dict(os.environ, {"MEMORY_STORE_DB": temp_db_path}):
        # Force reimport to pick up the new DB path
        import importlib

        import agent_memory_store.server as server_mod
        importlib.reload(server_mod)
        yield server_mod


class TestListTools:
    """Tests for the list_tools handler."""

    async def test_list_tools_returns_all_tools(self, server_module):
        """Test that all memory tools are listed."""
        tools = await server_module.list_tools()

        tool_names = {t.name for t in tools}
        assert tool_names == {"memory_store", "memory_recall", "memory_forget", "memory_list"}

    async def test_memory_store_tool_schema(self, server_module):
        """Test memory_store tool has correct schema."""
        tools = await server_module.list_tools()
        store_tool = next(t for t in tools if t.name == "memory_store")

        assert store_tool.description
        schema = store_tool.inputSchema
        assert schema["type"] == "object"
        assert "key" in schema["properties"]
        assert "value" in schema["properties"]
        assert schema["required"] == ["key", "value"]

    async def test_memory_recall_tool_schema(self, server_module):
        """Test memory_recall tool has correct schema."""
        tools = await server_module.list_tools()
        recall_tool = next(t for t in tools if t.name == "memory_recall")

        schema = recall_tool.inputSchema
        assert "key" in schema["properties"]
        assert "query" in schema["properties"]
        assert "namespace" in schema["properties"]
        assert "tags" in schema["properties"]

    async def test_memory_forget_tool_schema(self, server_module):
        """Test memory_forget tool has correct schema."""
        tools = await server_module.list_tools()
        forget_tool = next(t for t in tools if t.name == "memory_forget")

        schema = forget_tool.inputSchema
        assert schema["required"] == ["key"]

    async def test_memory_list_tool_schema(self, server_module):
        """Test memory_list tool has correct schema."""
        tools = await server_module.list_tools()
        list_tool = next(t for t in tools if t.name == "memory_list")

        schema = list_tool.inputSchema
        assert "namespace" in schema["properties"]
        assert "tags" in schema["properties"]
        assert "since_days" in schema["properties"]
        assert "limit" in schema["properties"]


class TestMemoryStoreTool:
    """Tests for the memory_store tool."""

    async def test_store_basic(self, server_module):
        """Test basic memory storage."""
        result = await server_module.call_tool(
            "memory_store", {"key": "test-key", "value": "test-value"}
        )

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["success"] is True
        assert "test-key" in data["message"]
        assert "id" in data

    async def test_store_with_namespace(self, server_module):
        """Test storing with namespace."""
        result = await server_module.call_tool(
            "memory_store",
            {"key": "ns-key", "value": "data", "namespace": "project:myapp"},
        )

        data = json.loads(result[0].text)
        assert data["namespace"] == "project:myapp"

    async def test_store_with_tags(self, server_module):
        """Test storing with tags."""
        result = await server_module.call_tool(
            "memory_store",
            {"key": "tagged", "value": "data", "tags": ["important", "work"]},
        )

        data = json.loads(result[0].text)
        assert data["success"] is True

    async def test_store_with_ttl(self, server_module):
        """Test storing with TTL."""
        result = await server_module.call_tool(
            "memory_store",
            {"key": "ephemeral", "value": "temporary", "ttl_days": 7},
        )

        data = json.loads(result[0].text)
        assert data["success"] is True


class TestMemoryRecallTool:
    """Tests for the memory_recall tool."""

    async def test_recall_by_key_found(self, server_module):
        """Test recalling by exact key."""
        # Store first
        await server_module.call_tool(
            "memory_store", {"key": "recall-test", "value": "secret data"}
        )

        # Recall
        result = await server_module.call_tool(
            "memory_recall", {"key": "recall-test"}
        )

        data = json.loads(result[0].text)
        assert data["success"] is True
        assert data["memory"]["value"] == "secret data"

    async def test_recall_by_key_not_found(self, server_module):
        """Test recalling non-existent key."""
        result = await server_module.call_tool(
            "memory_recall", {"key": "nonexistent"}
        )

        data = json.loads(result[0].text)
        assert data["success"] is False
        assert "not found" in data["message"].lower()

    async def test_recall_by_query(self, server_module):
        """Test full-text search."""
        # Store some memories
        await server_module.call_tool(
            "memory_store", {"key": "doc1", "value": "Python programming tutorial"}
        )
        await server_module.call_tool(
            "memory_store", {"key": "doc2", "value": "Rust programming guide"}
        )
        await server_module.call_tool(
            "memory_store", {"key": "doc3", "value": "Cooking recipes"}
        )

        # Search
        result = await server_module.call_tool(
            "memory_recall", {"query": "programming"}
        )

        data = json.loads(result[0].text)
        assert data["success"] is True
        assert data["count"] == 2

    async def test_recall_with_namespace_filter(self, server_module):
        """Test search with namespace filter."""
        await server_module.call_tool(
            "memory_store",
            {"key": "global1", "value": "searchable content", "namespace": "global"},
        )
        await server_module.call_tool(
            "memory_store",
            {"key": "project1", "value": "searchable content", "namespace": "project:x"},
        )

        result = await server_module.call_tool(
            "memory_recall", {"query": "searchable", "namespace": "project:x"}
        )

        data = json.loads(result[0].text)
        assert data["count"] == 1
        assert data["memories"][0]["key"] == "project1"

    async def test_recall_with_limit(self, server_module):
        """Test search respects limit."""
        for i in range(5):
            await server_module.call_tool(
                "memory_store", {"key": f"item{i}", "value": "common term"}
            )

        result = await server_module.call_tool(
            "memory_recall", {"query": "common", "limit": 2}
        )

        data = json.loads(result[0].text)
        assert len(data["memories"]) == 2

    async def test_recall_no_key_or_query(self, server_module):
        """Test error when neither key nor query provided."""
        result = await server_module.call_tool("memory_recall", {})

        data = json.loads(result[0].text)
        assert data["success"] is False
        assert "key or query" in data["message"].lower()

    async def test_recall_empty_key(self, server_module):
        """Test handling of empty key."""
        result = await server_module.call_tool("memory_recall", {"key": ""})

        data = json.loads(result[0].text)
        assert data["success"] is False


class TestMemoryForgetTool:
    """Tests for the memory_forget tool."""

    async def test_forget_existing(self, server_module):
        """Test deleting an existing memory."""
        await server_module.call_tool(
            "memory_store", {"key": "to-delete", "value": "bye"}
        )

        result = await server_module.call_tool(
            "memory_forget", {"key": "to-delete"}
        )

        data = json.loads(result[0].text)
        assert data["success"] is True
        assert "deleted" in data["message"].lower()

    async def test_forget_nonexistent(self, server_module):
        """Test deleting non-existent memory."""
        result = await server_module.call_tool(
            "memory_forget", {"key": "never-existed"}
        )

        data = json.loads(result[0].text)
        assert data["success"] is False
        assert "not found" in data["message"].lower()

    async def test_forget_then_recall(self, server_module):
        """Test that forgotten memory cannot be recalled."""
        await server_module.call_tool(
            "memory_store", {"key": "temp", "value": "data"}
        )
        await server_module.call_tool("memory_forget", {"key": "temp"})

        result = await server_module.call_tool("memory_recall", {"key": "temp"})

        data = json.loads(result[0].text)
        assert data["success"] is False


class TestMemoryListTool:
    """Tests for the memory_list tool."""

    async def test_list_all(self, server_module):
        """Test listing all memories."""
        await server_module.call_tool(
            "memory_store", {"key": "list1", "value": "a"}
        )
        await server_module.call_tool(
            "memory_store", {"key": "list2", "value": "b"}
        )

        result = await server_module.call_tool("memory_list", {})

        data = json.loads(result[0].text)
        assert data["success"] is True
        assert data["count"] == 2

    async def test_list_with_namespace(self, server_module):
        """Test listing with namespace filter."""
        await server_module.call_tool(
            "memory_store",
            {"key": "ns1", "value": "a", "namespace": "project:test"},
        )
        await server_module.call_tool(
            "memory_store",
            {"key": "ns2", "value": "b", "namespace": "global"},
        )

        result = await server_module.call_tool(
            "memory_list", {"namespace": "project:test"}
        )

        data = json.loads(result[0].text)
        assert data["count"] == 1
        assert data["memories"][0]["key"] == "ns1"

    async def test_list_with_tags(self, server_module):
        """Test listing with tags filter."""
        await server_module.call_tool(
            "memory_store",
            {"key": "tag1", "value": "a", "tags": ["urgent"]},
        )
        await server_module.call_tool(
            "memory_store",
            {"key": "tag2", "value": "b", "tags": ["normal"]},
        )

        result = await server_module.call_tool(
            "memory_list", {"tags": ["urgent"]}
        )

        data = json.loads(result[0].text)
        assert data["count"] == 1

    async def test_list_with_since_days(self, server_module):
        """Test listing with since_days filter."""
        await server_module.call_tool(
            "memory_store", {"key": "recent", "value": "new"}
        )

        result = await server_module.call_tool(
            "memory_list", {"since_days": 1}
        )

        data = json.loads(result[0].text)
        assert data["count"] >= 1

    async def test_list_with_limit(self, server_module):
        """Test listing respects limit."""
        for i in range(10):
            await server_module.call_tool(
                "memory_store", {"key": f"bulk{i}", "value": str(i)}
            )

        result = await server_module.call_tool("memory_list", {"limit": 3})

        data = json.loads(result[0].text)
        assert len(data["memories"]) == 3

    async def test_list_truncates_long_values(self, server_module):
        """Test that long values are truncated in list output."""
        long_value = "x" * 200
        await server_module.call_tool(
            "memory_store", {"key": "long", "value": long_value}
        )

        result = await server_module.call_tool("memory_list", {})

        data = json.loads(result[0].text)
        memory = data["memories"][0]
        assert len(memory["value"]) <= 103  # 100 chars + "..."
        assert memory["value"].endswith("...")

    async def test_list_includes_metadata(self, server_module):
        """Test that list includes expected metadata."""
        await server_module.call_tool(
            "memory_store",
            {"key": "meta", "value": "data", "tags": ["test"]},
        )

        result = await server_module.call_tool("memory_list", {})

        data = json.loads(result[0].text)
        memory = data["memories"][0]
        assert "key" in memory
        assert "value" in memory
        assert "namespace" in memory
        assert "tags" in memory
        assert "updated_at" in memory


class TestUnknownTool:
    """Tests for unknown tool handling."""

    async def test_unknown_tool(self, server_module):
        """Test calling an unknown tool."""
        result = await server_module.call_tool("unknown_tool", {})

        assert "Unknown tool" in result[0].text


class TestIntegrationScenarios:
    """End-to-end integration scenarios."""

    async def test_full_lifecycle(self, server_module):
        """Test complete memory lifecycle: store -> recall -> update -> forget."""
        # Store
        store_result = await server_module.call_tool(
            "memory_store",
            {"key": "lifecycle", "value": "initial", "tags": ["test"]},
        )
        assert json.loads(store_result[0].text)["success"]

        # Recall
        recall_result = await server_module.call_tool(
            "memory_recall", {"key": "lifecycle"}
        )
        assert json.loads(recall_result[0].text)["memory"]["value"] == "initial"

        # Update (store with same key)
        update_result = await server_module.call_tool(
            "memory_store",
            {"key": "lifecycle", "value": "updated"},
        )
        assert json.loads(update_result[0].text)["success"]

        # Verify update
        verify_result = await server_module.call_tool(
            "memory_recall", {"key": "lifecycle"}
        )
        assert json.loads(verify_result[0].text)["memory"]["value"] == "updated"

        # Forget
        forget_result = await server_module.call_tool(
            "memory_forget", {"key": "lifecycle"}
        )
        assert json.loads(forget_result[0].text)["success"]

        # Verify deletion
        final_result = await server_module.call_tool(
            "memory_recall", {"key": "lifecycle"}
        )
        assert not json.loads(final_result[0].text)["success"]

    async def test_multi_namespace_isolation(self, server_module):
        """Test that namespaces properly isolate memories."""
        # Store in different namespaces
        await server_module.call_tool(
            "memory_store",
            {"key": "shared-key", "value": "global-val", "namespace": "global"},
        )
        await server_module.call_tool(
            "memory_store",
            {"key": "project-key", "value": "project-val", "namespace": "project:a"},
        )
        await server_module.call_tool(
            "memory_store",
            {"key": "other-key", "value": "other-val", "namespace": "project:b"},
        )

        # List by namespace
        global_result = await server_module.call_tool(
            "memory_list", {"namespace": "global"}
        )
        project_a_result = await server_module.call_tool(
            "memory_list", {"namespace": "project:a"}
        )

        global_data = json.loads(global_result[0].text)
        project_data = json.loads(project_a_result[0].text)

        assert global_data["count"] == 1
        assert project_data["count"] == 1
        assert global_data["memories"][0]["key"] == "shared-key"
        assert project_data["memories"][0]["key"] == "project-key"

    async def test_search_and_filter_combined(self, server_module):
        """Test combining search with filters."""
        # Create test data
        await server_module.call_tool(
            "memory_store",
            {
                "key": "python-doc",
                "value": "Python documentation reference",
                "namespace": "docs",
                "tags": ["programming", "python"],
            },
        )
        await server_module.call_tool(
            "memory_store",
            {
                "key": "python-note",
                "value": "Personal Python notes",
                "namespace": "notes",
                "tags": ["programming", "python"],
            },
        )
        await server_module.call_tool(
            "memory_store",
            {
                "key": "rust-doc",
                "value": "Rust documentation reference",
                "namespace": "docs",
                "tags": ["programming", "rust"],
            },
        )

        # Search "Python" filtered to "docs" namespace
        result = await server_module.call_tool(
            "memory_recall",
            {"query": "Python", "namespace": "docs"},
        )

        data = json.loads(result[0].text)
        assert data["count"] == 1
        assert data["memories"][0]["key"] == "python-doc"
