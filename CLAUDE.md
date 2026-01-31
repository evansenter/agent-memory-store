# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

MCP server providing persistent key-value memory across Claude Code sessions. Features SQLite storage with FTS5 full-text search and optional sqlite-vec semantic search using sentence-transformers embeddings.

**Related**: [agent-event-bus](https://github.com/evansenter/agent-event-bus) and [agent-session-analytics](https://github.com/evansenter/agent-session-analytics) share design patterns.

**API Reference**: `memory --help` or `src/agent_memory_store/guide.md` (MCP resource: `agent-memory-store://guide`).

---

## DATABASE PROTECTION

**The database at `~/.claude/contrib/agent-memory-store/memories.db` contains irreplaceable memory data.**

### NEVER:
- Delete the database file
- `DROP TABLE` or `DELETE FROM` user data
- Add "reset" or "clear all" functionality

### Before schema changes:
```bash
cp ~/.claude/contrib/agent-memory-store/memories.db ~/.claude/contrib/agent-memory-store/memories.db.backup-$(date +%Y%m%d-%H%M%S)
```

### Safe operations:
- `make uninstall` - Preserves database
- `memory_forget(key)` - Single-key deletion (user-initiated)
- Schema migrations with column additions

---

## Commands

```bash
make check              # fmt + lint + test (run before pushing)
make install-server     # Install service + register MCP
make uninstall          # Remove service + MCP (preserves DB)
make dev                # Install with dev dependencies
uv sync --extra embeddings  # Enable semantic search

# Testing
pytest tests/test_storage.py::test_store_and_recall -v  # Single test
pytest tests/ -k "semantic" -v                          # Pattern match
```

### When to Restart

| Change | Action |
|--------|--------|
| `server.py`, `storage.py`, `embeddings.py`, `http_server.py` | Restart service |
| `cli.py` only | None (CLI runs fresh) |
| `guide.md` | None (read fresh each request) |
| `pyproject.toml` | `make install-server` |

## Architecture

```
src/agent_memory_store/
├── storage.py      # Core: MemoryStorage class, SQLite + FTS5 + sqlite-vec
├── server.py       # MCP server (stdio transport) - tool definitions
├── http_server.py  # HTTP wrapper (SSE transport) for remote access
├── embeddings.py   # Lazy-loaded sentence-transformers (optional)
├── cli.py          # CLI interface (memory command)
└── guide.md        # Usage guide exposed as MCP resource
```

**Data flow:** MCP tools (server.py) → MemoryStorage (storage.py) → SQLite

**Transport modes:**
- stdio: Direct MCP protocol via server.py (local Claude Code)
- HTTP/SSE: http_server.py wraps server.py for Tailscale access

**Storage layers:**
- `memories` table: Core key-value storage with metadata
- `memories_fts`: FTS5 virtual table (auto-synced via triggers)
- `memories_vec`: sqlite-vec virtual table for embeddings (optional)

## Key Types

```python
# storage.py
Memory          # Core data class: id, key, value, namespace, tags, importance, timestamps
QueryFilters    # Symbolic query parameters (RLM-inspired): regex, date ranges, importance
MemoryStats     # Aggregated statistics from explore()
ScoredMemory    # Memory with composite score (recency × importance × relevance)
```

## MCP Tools

| Tool | Purpose |
|------|---------|
| `memory_store` | Store with key, value, namespace, tags, ttl_days, importance |
| `memory_recall` | Retrieve by key or search (fts/semantic mode) |
| `memory_forget` | Delete by key |
| `memory_list` | List with filters |
| `memory_query` | Structured symbolic query (regex, date ranges, importance) |
| `memory_explore` | Get statistics before querying |
| `memory_search_weighted` | Recency × importance × relevance scoring |
| `memory_aggregate` | Group by namespace/tag/importance/date |

## API Design

CLI and MCP expose the same functionality:

| CLI | MCP | Notes |
|-----|-----|-------|
| `memory store` | `memory_store` | Same params |
| `memory recall` | `memory_recall` | CLI adds `--search`, `--value-only` |
| `memory query` | `memory_query` | Same symbolic filters |
| `memory search` | `memory_search_weighted` | Weighted scoring |

**When modifying API**: Update CLI args, MCP tool schema, and `guide.md` together.

---

## Design Philosophy

This API is consumed by LLMs. Design with that in mind:

1. **Don't over-distill** - Raw signals (`importance: 7, access_count: 12`) beat pre-computed interpretations
2. **Aggregate → drill-down** - `memory_explore` shows distribution, `memory_query` drills into specifics
3. **Self-play test** - Before merging, try reaching actionable conclusions using only MCP tools

---

## Tool Docstrings

Keep docstrings minimal - `guide.md` is the **canonical reference**. Docstrings add token overhead on every session.

**Include:**
- First-line description (what it does)
- Brief `Args:` section (one line per param)
- Non-obvious behavior

**Exclude (put in guide.md instead):**
- `Returns:` sections (JSON is self-documenting)
- Usage examples and patterns
- Implementation details

---

## Operations

```bash
# Watch server activity
tail -f ~/.claude/contrib/agent-memory-store/agent-memory-store.log

# Override database path
MEMORY_STORE_DB=/path/to/db.sqlite memory explore

# Disable Tailscale auth (for local dev)
AUTH_DISABLED=1 uvicorn agent_memory_store.http_server:app
```

## Testing Notes

- Tests use `temp_db` fixture (conftest.py) for isolated databases
- Semantic tests may be skipped if sentence-transformers not installed
- CLI tests use argparse mocking via `main(argv=[...])` pattern
