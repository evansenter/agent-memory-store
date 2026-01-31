# agent-memory-store

**MCP server for shared persistent memory across Claude Code sessions.**

## Problem

Each Claude Code session is isolated. When context gets truncated or a session ends, learnings are lost unless manually written to files. There's no way for:
- Sessions to share knowledge ("I figured out the API works like X")
- Agents to build on each other's discoveries
- Cross-session continuity without file discipline

## Solution

An HTTP MCP server (same pattern as agent-event-bus) that provides:
- Persistent key-value + semantic memory
- Session-aware scoping
- Tailscale-secured for multi-machine access

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     agent-memory-store                          │
│                                                                 │
│  HTTP MCP Server (localhost:8082)                              │
│  ├── SQLite backend (memories.db)                              │
│  ├── sqlite-vec for embeddings (optional)                      │
│  └── Tailscale identity for auth                               │
│                                                                 │
│  Storage:                                                       │
│  ├── memories table (id, key, value, embedding, metadata)      │
│  ├── Full-text search via FTS5                                 │
│  └── Vector search via sqlite-vec (if embeddings enabled)      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## MCP Tools

### `memory_store`
Store a memory with optional tags and TTL.

```json
{
  "key": "api-auth-pattern",
  "value": "The Foo API requires Bearer tokens with scope=read",
  "tags": ["foo-project", "api", "auth"],
  "ttl_days": null,
  "namespace": "global"
}
```

**Namespaces:**
- `global` — Shared across all sessions
- `project:{name}` — Scoped to a project
- `session:{id}` — Private to a session (rarely used)

### `memory_recall`
Retrieve memories by query (semantic or exact).

```json
{
  "query": "how does Foo API authentication work",
  "mode": "semantic",
  "namespace": "global",
  "tags": ["foo-project"],
  "limit": 5
}
```

**Modes:**
- `exact` — Key lookup
- `search` — FTS5 full-text search
- `semantic` — Vector similarity (requires embeddings)

### `memory_forget`
Delete memories by key or query.

```json
{
  "key": "api-auth-pattern"
}
// or
{
  "query": "outdated API patterns",
  "mode": "semantic",
  "confirm": true
}
```

### `memory_list`
List memories with filters.

```json
{
  "namespace": "project:foo",
  "tags": ["api"],
  "since": "2026-01-01",
  "limit": 20
}
```

## Schema

```sql
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    key TEXT UNIQUE,
    value TEXT NOT NULL,
    namespace TEXT DEFAULT 'global',
    tags TEXT,  -- JSON array
    embedding BLOB,  -- sqlite-vec F32_BLOB
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT,  -- session/agent identity
    expires_at TEXT,  -- optional TTL
    access_count INTEGER DEFAULT 0,
    last_accessed_at TEXT
);

CREATE VIRTUAL TABLE memories_fts USING fts5(key, value, content=memories);
CREATE VIRTUAL TABLE memories_vec USING vec0(embedding float[1536]);
```

## Embedding Strategy

**Option A: Local embeddings (recommended for privacy)**
- Use `sentence-transformers` with a small model (all-MiniLM-L6-v2)
- ~80MB model, runs locally
- No API costs

**Option B: API embeddings**
- OpenAI text-embedding-3-small
- Better quality, but requires API key + costs

**Option C: No embeddings**
- FTS5 only, no semantic search
- Simplest, still useful

## Identity & Access

Same pattern as agent-event-bus:
- Localhost connections trusted (bypass auth)
- Remote connections require Tailscale identity header
- `created_by` tracks which session stored the memory

## Integration with Existing Stack

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ agent-event-bus │     │ agent-memory-   │     │ agent-session-  │
│    (coord)      │     │    store        │     │   analytics     │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┴───────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │   Claude Code Session   │
                    └─────────────────────────┘
```

Sessions can:
1. Store learnings in memory-store
2. Announce discoveries via event-bus
3. Query past sessions via session-analytics

## Installation

Same pattern as siblings:

```bash
git clone https://github.com/evansenter/agent-memory-store.git
cd agent-memory-store
make install-server  # systemd + MCP config + tailscale serve
```

Client:
```bash
make install-client REMOTE_URL=https://speck-vm.tailac7b3c.ts.net/agent-memory-store/mcp
```

## CLI

```bash
# Store a memory
agent-memory-store-cli store "api-pattern" "Use Bearer tokens" --tags api,auth

# Recall
agent-memory-store-cli recall "how does auth work" --mode semantic

# List recent
agent-memory-store-cli list --since 7d --namespace global
```

## Open Questions

1. **Embedding model choice** — Local vs API? Default to local for simplicity?
2. **Garbage collection** — Auto-expire unused memories? LRU eviction?
3. **Conflict resolution** — What if two sessions store the same key?
4. **Import/export** — Should support dumping to markdown for backup?
5. **Integration with MEMORY.md** — Should this replace file-based memory, or complement it?

## Success Metrics

- Sessions can share knowledge without file coordination
- Semantic recall finds relevant memories even with different wording
- No manual memory discipline required (agents just `memory_store` as they learn)
- Survives context truncation (memories persist in SQLite)

## Prior Art

- `@modelcontextprotocol/server-memory` — Knowledge graph, no semantic search
- `mem0-mcp` — Cloud-based, semantic, but external dependency
- MemGPT — OS-inspired memory hierarchy, more complex
