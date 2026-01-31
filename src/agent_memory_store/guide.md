# Agent Memory Store Usage Guide

> **Tip:** Read this guide via the MCP resource `agent-memory-store://guide` for usage patterns and best practices.

## What is this?

Agent Memory Store provides persistent key-value memory for Claude Code sessions. Memories
survive across sessions and can be searched using full-text search (FTS5) or semantic
similarity search (with optional embeddings).

## Available Tools

| Tool | Purpose |
|------|---------|
| `memory_store` | Store a memory with key, value, importance |
| `memory_recall` | Retrieve by key or search (fts/semantic) |
| `memory_forget` | Delete a memory by key |
| `memory_list` | List memories with filters |
| `memory_query` | Structured query (regex, date ranges, importance) |
| `memory_explore` | Get statistics before querying |
| `memory_search_weighted` | Recency × importance × relevance scoring |
| `memory_aggregate` | Group by namespace/tag/importance/date |

## Quick Start

### 1. Store a memory
```
memory_store(
  key="project-auth-decision",
  value="Using JWT with refresh tokens for auth",
  namespace="project:myapp",
  tags=["architecture", "auth"]
)
→ {success: true, id: "abc123", namespace: "project:myapp"}
```

### 2. Recall by exact key
```
memory_recall(key="project-auth-decision")
→ {success: true, memory: {key: "...", value: "Using JWT...", ...}}
```

### 3. Search with full-text
```
memory_recall(query="authentication tokens", mode="fts")
→ {success: true, count: 2, memories: [...]}
```

### 4. Search semantically (if embeddings installed)
```
memory_recall(query="how do we handle user login?", mode="semantic")
→ {success: true, mode: "semantic", count: 3, memories: [{..., score: 0.89}, ...]}
```

### 5. List recent memories
```
memory_list(since_days=7, limit=10)
→ {success: true, count: 10, memories: [...]}
```

### 6. Forget a memory
```
memory_forget(key="obsolete-note")
→ {success: true, message: "Deleted: obsolete-note"}
```

## Namespaces

Namespaces organize memories by scope:

| Namespace | When to Use |
|-----------|-------------|
| `global` | Cross-project knowledge (default) |
| `project:{name}` | Project-specific decisions, context |
| `session:{id}` | Temporary session-specific notes |

```
memory_store(key="api-pattern", value="...", namespace="project:myapp")
memory_list(namespace="project:myapp")  # Only this project's memories
```

## Tags

Tags enable flexible categorization and filtering:

```
memory_store(
  key="error-handling",
  value="Use Result type for errors",
  tags=["pattern", "rust", "error-handling"]
)

memory_recall(query="error", tags=["rust"])  # Filter by tag
memory_list(tags=["pattern"])  # List all patterns
```

## Search Modes

### FTS5 (Full-Text Search) - Default
- Searches key, value, and tags
- Fast exact and prefix matching
- Good for known terms

```
memory_recall(query="authentication", mode="fts")
```

### Semantic Search (requires embeddings)
- Uses AI embeddings for meaning-based search
- Finds conceptually related content
- Returns similarity scores (0-1)

```
memory_recall(query="how do users log in?", mode="semantic")
→ {..., mode: "semantic", memories: [{..., score: 0.85}]}
```

**Fallback behavior:** If semantic search is unavailable (embeddings not installed),
it automatically falls back to FTS5 and returns `mode: "fts_fallback"`.

## Enabling Semantic Search

Semantic search requires the optional `embeddings` extra:

```bash
# Install with embeddings support
pip install agent-memory-store[embeddings]

# Or with uv
uv sync --extra embeddings
```

This installs `sentence-transformers` with the `all-MiniLM-L6-v2` model (~80MB).

## TTL (Time-To-Live)

Set automatic expiration for temporary memories:

```
memory_store(
  key="temp-context",
  value="Working on feature X",
  ttl_days=7  # Expires in 7 days
)
```

Memories without TTL persist indefinitely.

## Common Patterns

### Store project decisions
```
memory_store(
  key="db-choice-2024",
  value="Chose PostgreSQL over MySQL for JSON support and better indexing",
  namespace="project:myapp",
  tags=["architecture", "database", "decision"]
)
```

### Remember gotchas
```
memory_store(
  key="gotcha-docker-m1",
  value="Docker on M1: use --platform linux/amd64 for x86 images",
  tags=["gotcha", "docker", "m1"]
)
```

### Track learned patterns
```
memory_store(
  key="pattern-error-handling",
  value="In this codebase, use AppError enum with thiserror for all errors",
  namespace="project:myapp",
  tags=["pattern", "error-handling"]
)
```

### Session handoff context
```
memory_store(
  key="session-context-20240115",
  value="Working on auth refactor. PR #42 in progress. Blocked on API review.",
  namespace="session:abc123",
  ttl_days=1
)
```

## Best Practices

1. **Use meaningful keys** - `auth-jwt-decision` not `note1`
2. **Namespace appropriately** - `project:` for project-specific, `global` for universal
3. **Tag consistently** - Use lowercase, hyphenated tags
4. **Keep values concise** - Memory, not documentation
5. **Set TTL for temporary data** - Avoid clutter from stale session notes
6. **Use semantic search for discovery** - "What do I know about X?"
7. **Use FTS for precision** - When you know the exact terms

## Data Storage

| Item | Path |
|------|------|
| Database | `~/.claude/contrib/agent-memory-store/memories.db` |

The database uses SQLite with:
- FTS5 virtual table for full-text search
- sqlite-vec for vector embeddings (if enabled)
- Automatic index synchronization via triggers

## API Reference

### memory_store
```
memory_store(
  key: str,           # Unique identifier (required)
  value: str,         # Content to store (required)
  namespace: str,     # Scope: "global", "project:X", "session:X" (default: "global")
  tags: list[str],    # Categorization tags (optional)
  ttl_days: int,      # Days until expiration (optional)
  importance: int     # Priority 1-10 (default: 5)
)
```

### memory_recall
```
memory_recall(
  key: str,           # Exact key lookup (mutually exclusive with query)
  query: str,         # Search query (mutually exclusive with key)
  mode: str,          # "fts" or "semantic" (default: "fts")
  namespace: str,     # Filter by namespace (optional)
  tags: list[str],    # Filter by tags (optional)
  limit: int          # Max results (default: 10)
)
```

### memory_forget
```
memory_forget(
  key: str            # Key to delete (required)
)
```

### memory_list
```
memory_list(
  namespace: str,     # Filter by namespace (optional)
  tags: list[str],    # Filter by tags (optional)
  since_days: int,    # Only memories from last N days (optional)
  limit: int          # Max results (default: 20)
)
```

### memory_query
Structured query with symbolic filters. Use for precise, programmatic exploration.

```
memory_query(
  key_pattern: str,     # Regex pattern for keys (optional)
  value_pattern: str,   # Regex pattern for values (optional)
  text_contains: str,   # Substring in key or value (optional)
  namespace: str,       # Filter by namespace (optional)
  tags: list[str],      # Match any of these tags (optional)
  has_all_tags: list,   # Match ALL of these tags (optional)
  min_importance: int,  # Minimum importance 1-10 (optional)
  max_importance: int,  # Maximum importance 1-10 (optional)
  created_after: str,   # ISO datetime (optional)
  created_before: str,  # ISO datetime (optional)
  updated_after: str,   # ISO datetime (optional)
  min_access_count: int,# Minimum access count (optional)
  never_accessed: bool, # Only unaccessed memories (optional)
  order_by: str,        # "created_at", "updated_at", "importance", "access_count", "key"
  order_desc: bool,     # Sort descending (default: true)
  limit: int,           # Max results (default: 50)
  offset: int           # Pagination offset (default: 0)
)
```

### memory_explore
Get statistics about the memory store before querying.

```
memory_explore()
→ {
    total_count: 42,
    namespaces: {"global": 30, "project:myapp": 12},
    top_tags: {"pattern": 8, "gotcha": 5, ...},
    importance_distribution: {"5": 20, "7": 10, ...},
    date_range: {oldest: "2024-01-01T...", newest: "2024-03-15T..."},
    avg_importance: 5.2,
    semantic_available: true
  }
```

### memory_search_weighted
Search with combined recency × importance × relevance scoring.

```
memory_search_weighted(
  query: str,             # Search query (required)
  namespace: str,         # Filter by namespace (optional)
  tags: list[str],        # Filter by tags (optional)
  limit: int,             # Max results (default: 10)
  recency_weight: float,  # Weight for recency (default: 1.0)
  importance_weight: float, # Weight for importance (default: 1.0)
  relevance_weight: float,  # Weight for FTS relevance (default: 1.0)
  recency_decay_days: float # Days until recency decays to ~37% (default: 30)
)
→ {memories: [{..., score: 0.85, recency_score: 0.9, importance_score: 0.7, relevance_score: 0.8}]}
```

### memory_aggregate
Group memories by dimension without loading full content.

```
memory_aggregate(
  group_by: str,        # "namespace", "tag", "importance", or "date"
  namespace: str,       # Pre-filter by namespace (optional)
  min_importance: int   # Pre-filter by importance (optional)
)
→ {group_by: "namespace", groups: {"global": 30, "project:myapp": 12}}
```
