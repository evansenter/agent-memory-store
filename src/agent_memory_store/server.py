"""MCP server for agent-memory-store."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

from .storage import MemoryStorage, QueryFilters

# Initialize storage
DB_PATH = os.environ.get("MEMORY_STORE_DB", Path.home() / ".claude" / "contrib" / "agent-memory-store" / "memories.db")
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
storage = MemoryStorage(DB_PATH)

# Create server
server = Server("agent-memory-store")

# Guide resource
GUIDE_URI = "agent-memory-store://guide"


@server.list_resources()
async def list_resources() -> list[types.Resource]:
    """List available resources."""
    return [
        types.Resource(
            uri=GUIDE_URI,
            name="Usage Guide",
            description="Usage guide and API reference for agent-memory-store",
            mimeType="text/markdown",
        )
    ]


@server.read_resource()
async def read_resource(uri: str) -> str:
    """Read a resource by URI."""
    if str(uri) == GUIDE_URI:
        guide_path = Path(__file__).parent / "guide.md"
        try:
            return guide_path.read_text()
        except FileNotFoundError:
            return "# Agent Memory Store\n\nGuide file not found."
    raise ValueError(f"Unknown resource: {uri}")


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
        # Symbolic Query Layer (RLM-inspired)
        types.Tool(
            name="memory_query",
            description="Execute structured queries with symbolic filters (regex, date ranges, importance). "
            "Use this for code-based memory exploration before semantic search.",
            inputSchema={
                "type": "object",
                "properties": {
                    "key_pattern": {
                        "type": "string",
                        "description": "Regex pattern to match memory keys",
                    },
                    "value_pattern": {
                        "type": "string",
                        "description": "Regex pattern to match memory values",
                    },
                    "text_contains": {
                        "type": "string",
                        "description": "Substring to find in key or value",
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Filter by namespace",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Match memories with any of these tags",
                    },
                    "has_all_tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Match memories with ALL of these tags",
                    },
                    "min_importance": {
                        "type": "integer",
                        "description": "Minimum importance (1-10)",
                    },
                    "max_importance": {
                        "type": "integer",
                        "description": "Maximum importance (1-10)",
                    },
                    "created_after": {
                        "type": "string",
                        "description": "ISO datetime - only memories created after this",
                    },
                    "created_before": {
                        "type": "string",
                        "description": "ISO datetime - only memories created before this",
                    },
                    "updated_after": {
                        "type": "string",
                        "description": "ISO datetime - only memories updated after this",
                    },
                    "min_access_count": {
                        "type": "integer",
                        "description": "Minimum times accessed",
                    },
                    "never_accessed": {
                        "type": "boolean",
                        "description": "Only memories never accessed",
                    },
                    "order_by": {
                        "type": "string",
                        "enum": ["created_at", "updated_at", "importance", "access_count", "key"],
                        "description": "Sort field",
                        "default": "updated_at",
                    },
                    "order_desc": {
                        "type": "boolean",
                        "description": "Sort descending",
                        "default": True,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results",
                        "default": 50,
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Skip first N results (pagination)",
                        "default": 0,
                    },
                },
            },
        ),
        types.Tool(
            name="memory_explore",
            description="Get statistics about the memory store: counts, namespaces, tags, importance distribution. "
            "Use this to understand what's available before querying.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        types.Tool(
            name="memory_search_weighted",
            description="Search with combined recency × importance × relevance scoring (Generative Agents model). "
            "Returns memories ranked by weighted combination of how recent, how important, and how relevant.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for relevance scoring",
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
                        "description": "Maximum results",
                        "default": 10,
                    },
                    "recency_weight": {
                        "type": "number",
                        "description": "Weight for recency component",
                        "default": 1.0,
                    },
                    "importance_weight": {
                        "type": "number",
                        "description": "Weight for importance component",
                        "default": 1.0,
                    },
                    "relevance_weight": {
                        "type": "number",
                        "description": "Weight for relevance component",
                        "default": 1.0,
                    },
                    "recency_decay_days": {
                        "type": "number",
                        "description": "Days until recency score decays to ~37%",
                        "default": 30.0,
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="memory_aggregate",
            description="Aggregate memories by namespace, tag, importance, or date. "
            "Get counts without loading all memory content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "group_by": {
                        "type": "string",
                        "enum": ["namespace", "tag", "importance", "date"],
                        "description": "Dimension to group by",
                        "default": "namespace",
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Filter by namespace before aggregating",
                    },
                    "min_importance": {
                        "type": "integer",
                        "description": "Filter by minimum importance before aggregating",
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

            since = datetime.now(UTC) - timedelta(days=arguments["since_days"])

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

    elif name == "memory_query":
        # Build QueryFilters from arguments
        filters = QueryFilters(
            key_pattern=arguments.get("key_pattern"),
            value_pattern=arguments.get("value_pattern"),
            text_contains=arguments.get("text_contains"),
            namespace=arguments.get("namespace"),
            tags=arguments.get("tags"),
            has_all_tags=arguments.get("has_all_tags"),
            min_importance=arguments.get("min_importance"),
            max_importance=arguments.get("max_importance"),
            min_access_count=arguments.get("min_access_count"),
            never_accessed=arguments.get("never_accessed", False),
            order_by=arguments.get("order_by", "updated_at"),
            order_desc=arguments.get("order_desc", True),
            limit=arguments.get("limit", 50),
            offset=arguments.get("offset", 0),
        )

        # Parse datetime strings
        if arguments.get("created_after"):
            filters.created_after = datetime.fromisoformat(arguments["created_after"])
        if arguments.get("created_before"):
            filters.created_before = datetime.fromisoformat(arguments["created_before"])
        if arguments.get("updated_after"):
            filters.updated_after = datetime.fromisoformat(arguments["updated_after"])

        memories = storage.query(filters)
        return [
            types.TextContent(
                type="text",
                text=json.dumps(
                    {
                        "success": True,
                        "count": len(memories),
                        "offset": filters.offset,
                        "limit": filters.limit,
                        "memories": [
                            {
                                "key": m.key,
                                "value": m.value[:200] + "..." if len(m.value) > 200 else m.value,
                                "namespace": m.namespace,
                                "tags": m.tags,
                                "importance": m.importance,
                                "created_at": m.created_at.isoformat(),
                                "updated_at": m.updated_at.isoformat(),
                                "access_count": m.access_count,
                            }
                            for m in memories
                        ],
                    }
                ),
            )
        ]

    elif name == "memory_explore":
        stats = storage.explore()
        return [
            types.TextContent(
                type="text",
                text=json.dumps(
                    {
                        "success": True,
                        "total_count": stats.total_count,
                        "namespaces": stats.namespaces,
                        "top_tags": stats.tags,
                        "importance_distribution": stats.importance_distribution,
                        "date_range": {
                            "oldest": stats.date_range[0].isoformat() if stats.date_range[0] else None,
                            "newest": stats.date_range[1].isoformat() if stats.date_range[1] else None,
                        },
                        "avg_importance": stats.avg_importance,
                        "total_access_count": stats.total_access_count,
                        "semantic_available": stats.semantic_available,
                    }
                ),
            )
        ]

    elif name == "memory_search_weighted":
        results = storage.search_weighted(
            query=arguments["query"],
            namespace=arguments.get("namespace"),
            tags=arguments.get("tags"),
            limit=arguments.get("limit", 10),
            recency_weight=arguments.get("recency_weight", 1.0),
            importance_weight=arguments.get("importance_weight", 1.0),
            relevance_weight=arguments.get("relevance_weight", 1.0),
            recency_decay_days=arguments.get("recency_decay_days", 30.0),
        )
        return [
            types.TextContent(
                type="text",
                text=json.dumps(
                    {
                        "success": True,
                        "count": len(results),
                        "memories": [
                            {
                                "key": sm.memory.key,
                                "value": sm.memory.value[:200] + "..." if len(sm.memory.value) > 200 else sm.memory.value,
                                "namespace": sm.memory.namespace,
                                "tags": sm.memory.tags,
                                "importance": sm.memory.importance,
                                "score": round(sm.score, 4),
                                "recency_score": round(sm.recency_score, 4),
                                "importance_score": round(sm.importance_score, 4),
                                "relevance_score": round(sm.relevance_score, 4),
                            }
                            for sm in results
                        ],
                    }
                ),
            )
        ]

    elif name == "memory_aggregate":
        # Build filters if any filter params provided
        filters = None
        if arguments.get("namespace") or arguments.get("min_importance"):
            filters = QueryFilters(
                namespace=arguments.get("namespace"),
                min_importance=arguments.get("min_importance"),
                limit=10000,  # High limit for aggregation
            )

        result = storage.aggregate(
            group_by=arguments.get("group_by", "namespace"),
            filters=filters,
        )
        return [
            types.TextContent(
                type="text",
                text=json.dumps({"success": True, **result}),
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
