"""MCP server for agent-memory-store."""

import json
import os
from datetime import datetime
from pathlib import Path

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

from .storage import MemoryStorage

# Initialize storage
DB_PATH = os.environ.get("MEMORY_STORE_DB", Path.home() / ".claude" / "contrib" / "agent-memory-store" / "memories.db")
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
storage = MemoryStorage(DB_PATH)

# Create server
server = Server("agent-memory-store")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """List available memory tools."""
    return [
        types.Tool(
            name="memory_store",
            description="Store a memory with a key, value, and optional tags/namespace",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Unique identifier for this memory",
                    },
                    "value": {
                        "type": "string",
                        "description": "The content to remember",
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Scope: 'global', 'project:name', or 'session:id'",
                        "default": "global",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for categorization",
                    },
                    "ttl_days": {
                        "type": "integer",
                        "description": "Days until memory expires (optional)",
                    },
                },
                "required": ["key", "value"],
            },
        ),
        types.Tool(
            name="memory_recall",
            description="Retrieve memories by key or search query",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Exact key to retrieve",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query (full-text or semantic)",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["fts", "semantic"],
                        "description": "Search mode: 'fts' or 'semantic' (vector similarity)",
                        "default": "fts",
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Filter by namespace",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by tags",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return",
                        "default": 10,
                    },
                },
            },
        ),
        types.Tool(
            name="memory_forget",
            description="Delete a memory by key",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Key of memory to delete",
                    },
                },
                "required": ["key"],
            },
        ),
        types.Tool(
            name="memory_list",
            description="List memories with optional filters",
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {
                        "type": "string",
                        "description": "Filter by namespace",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by tags",
                    },
                    "since_days": {
                        "type": "integer",
                        "description": "Only memories from last N days",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results",
                        "default": 20,
                    },
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Handle tool calls."""
    if name == "memory_store":
        memory = storage.store(
            key=arguments["key"],
            value=arguments["value"],
            namespace=arguments.get("namespace", "global"),
            tags=arguments.get("tags"),
            ttl_days=arguments.get("ttl_days"),
        )
        return [
            types.TextContent(
                type="text",
                text=json.dumps(
                    {
                        "success": True,
                        "message": f"Stored memory: {memory.key}",
                        "id": memory.id,
                        "namespace": memory.namespace,
                    }
                ),
            )
        ]

    elif name == "memory_recall":
        if "key" in arguments and arguments["key"]:
            memory = storage.recall_by_key(arguments["key"])
            if memory:
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "success": True,
                                "memory": {
                                    "key": memory.key,
                                    "value": memory.value,
                                    "namespace": memory.namespace,
                                    "tags": memory.tags,
                                    "created_at": memory.created_at.isoformat(),
                                },
                            }
                        ),
                    )
                ]
            else:
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps({"success": False, "message": "Memory not found"}),
                    )
                ]

        elif "query" in arguments and arguments["query"]:
            mode = arguments.get("mode", "fts")
            limit = arguments.get("limit", 10)
            namespace = arguments.get("namespace")
            tags = arguments.get("tags")

            if mode == "semantic":
                # Semantic search returns (memory, score) tuples
                results = storage.search_semantic(
                    query=arguments["query"],
                    namespace=namespace,
                    tags=tags,
                    limit=limit,
                )
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "success": True,
                                "mode": (
                                    "semantic" if storage.semantic_available else "fts_fallback"
                                ),
                                "count": len(results),
                                "memories": [
                                    {
                                        "key": m.key,
                                        "value": m.value,
                                        "namespace": m.namespace,
                                        "tags": m.tags,
                                        "score": round(score, 4),
                                    }
                                    for m, score in results
                                ],
                            }
                        ),
                    )
                ]
            else:
                # FTS search
                memories = storage.search(
                    query=arguments["query"],
                    namespace=namespace,
                    tags=tags,
                    limit=limit,
                )
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "success": True,
                                "mode": "fts",
                                "count": len(memories),
                                "memories": [
                                    {
                                        "key": m.key,
                                        "value": m.value,
                                        "namespace": m.namespace,
                                        "tags": m.tags,
                                    }
                                    for m in memories
                                ],
                            }
                        ),
                    )
                ]
        else:
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({"success": False, "message": "Provide key or query"}),
                )
            ]

    elif name == "memory_forget":
        deleted = storage.forget(arguments["key"])
        return [
            types.TextContent(
                type="text",
                text=json.dumps(
                    {
                        "success": deleted,
                        "message": f"{'Deleted' if deleted else 'Not found'}: {arguments['key']}",
                    }
                ),
            )
        ]

    elif name == "memory_list":
        since = None
        if "since_days" in arguments:
            from datetime import timedelta

            since = datetime.utcnow() - timedelta(days=arguments["since_days"])

        memories = storage.list_memories(
            namespace=arguments.get("namespace"),
            tags=arguments.get("tags"),
            since=since,
            limit=arguments.get("limit", 20),
        )
        return [
            types.TextContent(
                type="text",
                text=json.dumps(
                    {
                        "success": True,
                        "count": len(memories),
                        "memories": [
                            {
                                "key": m.key,
                                "value": m.value[:100] + "..." if len(m.value) > 100 else m.value,
                                "namespace": m.namespace,
                                "tags": m.tags,
                                "updated_at": m.updated_at.isoformat(),
                            }
                            for m in memories
                        ],
                    }
                ),
            )
        ]

    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    """Run the MCP server."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
