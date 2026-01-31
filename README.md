# agent-memory-store

MCP server providing persistent key-value memory across Claude Code sessions.

## Features

- **Persistent storage** - Memories survive context truncation and session ends
- **Full-text search** - FTS5-powered search across keys, values, and tags
- **Semantic search** - Optional embeddings for meaning-based retrieval
- **Namespace scoping** - Organize by `global`, `project:{name}`, or `session:{id}`
- **Importance scoring** - Prioritize memories with 1-10 importance levels
- **TTL support** - Automatic expiration for temporary memories
- **Multi-machine access** - Tailscale-secured HTTP transport

## Installation

### Server (where the database lives)

```bash
git clone https://github.com/evansenter/agent-memory-store.git
cd agent-memory-store
make install-server  # systemd + MCP config + tailscale serve
```

### Client (connects to remote server)

```bash
make install-client REMOTE_URL=https://your-host.ts.net/agent-memory-store/mcp
```

### Enable semantic search (optional)

```bash
uv sync --extra embeddings
# or: pip install agent-memory-store[embeddings]
```

Installs `sentence-transformers` with `all-MiniLM-L6-v2` (~80MB).

## Quick Start

### Store a memory

```bash
memory store "api-pattern" "Use Bearer tokens for Foo API" --tags api,auth
```

### Recall by key

```bash
memory recall --key "api-pattern"
```

### Search memories

```bash
memory recall --search "authentication"
```

### Semantic search

```bash
memory recall --search "how does auth work" --mode semantic
```

### List recent memories

```bash
memory list --since-days 7
```

## MCP Tools

| Tool | Purpose |
|------|---------|
| `memory_store` | Store with key, value, namespace, tags, importance, ttl |
| `memory_recall` | Retrieve by key or search (fts/semantic) |
| `memory_forget` | Delete by key |
| `memory_list` | List with filters |
| `memory_query` | Structured query (regex, dates, importance) |
| `memory_explore` | Get statistics before querying |
| `memory_search_weighted` | Recency x importance x relevance scoring |
| `memory_aggregate` | Group by namespace/tag/importance/date |

See [guide.md](src/agent_memory_store/guide.md) or access via MCP resource `agent-memory-store://guide`.

## Architecture

```
Claude Code Session
        |
        v
    MCP Protocol (stdio or HTTP/SSE)
        |
        v
    agent-memory-store
    ├── SQLite + FTS5 (full-text search)
    └── sqlite-vec (semantic embeddings, optional)
```

**Data location:** `~/.claude/contrib/agent-memory-store/memories.db`

## Related Projects

- [agent-event-bus](https://github.com/evansenter/agent-event-bus) - Cross-session coordination
- [agent-session-analytics](https://github.com/evansenter/agent-session-analytics) - Session analytics and patterns

## License

MIT
