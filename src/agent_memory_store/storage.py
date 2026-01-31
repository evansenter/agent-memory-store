"""SQLite storage backend for memories."""

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class Memory:
    """A stored memory."""

    id: str
    key: str
    value: str
    namespace: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    expires_at: Optional[datetime] = None
    access_count: int = 0
    last_accessed_at: Optional[datetime] = None


class MemoryStorage:
    """SQLite-backed memory storage with FTS5 search."""

    def __init__(self, db_path: str | Path = "memories.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    namespace TEXT DEFAULT 'global',
                    tags TEXT DEFAULT '[]',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT,
                    expires_at TEXT,
                    access_count INTEGER DEFAULT 0,
                    last_accessed_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_memories_namespace ON memories(namespace);
                CREATE INDEX IF NOT EXISTS idx_memories_expires ON memories(expires_at);
            """)

            # Create FTS5 virtual table if not exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='memories_fts'"
            )
            if not cursor.fetchone():
                conn.execute("""
                    CREATE VIRTUAL TABLE memories_fts USING fts5(
                        key, value, tags,
                        content=memories,
                        content_rowid=rowid
                    )
                """)
                # Create triggers to keep FTS in sync
                conn.executescript("""
                    CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                        INSERT INTO memories_fts(rowid, key, value, tags)
                        VALUES (NEW.rowid, NEW.key, NEW.value, NEW.tags);
                    END;

                    CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, key, value, tags)
                        VALUES ('delete', OLD.rowid, OLD.key, OLD.value, OLD.tags);
                    END;

                    CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, key, value, tags)
                        VALUES ('delete', OLD.rowid, OLD.key, OLD.value, OLD.tags);
                        INSERT INTO memories_fts(rowid, key, value, tags)
                        VALUES (NEW.rowid, NEW.key, NEW.value, NEW.tags);
                    END;
                """)

    def store(
        self,
        key: str,
        value: str,
        namespace: str = "global",
        tags: list[str] | None = None,
        created_by: str | None = None,
        ttl_days: int | None = None,
    ) -> Memory:
        """Store a memory, replacing if key exists."""
        memory_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        tags_json = json.dumps(tags or [])
        expires_at = None
        if ttl_days:
            from datetime import timedelta

            expires_at = (datetime.utcnow() + timedelta(days=ttl_days)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO memories (id, key, value, namespace, tags, created_at, updated_at, created_by, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    namespace = excluded.namespace,
                    tags = excluded.tags,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at
                """,
                (memory_id, key, value, namespace, tags_json, now, now, created_by, expires_at),
            )

        return Memory(
            id=memory_id,
            key=key,
            value=value,
            namespace=namespace,
            tags=tags or [],
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
            created_by=created_by,
            expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
        )

    def recall_by_key(self, key: str) -> Memory | None:
        """Retrieve a memory by exact key."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM memories WHERE key = ?",
                (key,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            # Update access stats
            conn.execute(
                """
                UPDATE memories
                SET access_count = access_count + 1, last_accessed_at = ?
                WHERE key = ?
                """,
                (datetime.utcnow().isoformat(), key),
            )

            return self._row_to_memory(row)

    def search(
        self,
        query: str,
        namespace: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[Memory]:
        """Full-text search memories."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Build query with optional filters
            sql = """
                SELECT m.* FROM memories m
                JOIN memories_fts fts ON m.rowid = fts.rowid
                WHERE memories_fts MATCH ?
            """
            params: list = [query]

            if namespace:
                sql += " AND m.namespace = ?"
                params.append(namespace)

            sql += " ORDER BY rank LIMIT ?"
            params.append(limit)

            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()

            memories = [self._row_to_memory(row) for row in rows]

            # Filter by tags if specified (done in Python for simplicity)
            if tags:
                memories = [m for m in memories if any(t in m.tags for t in tags)]

            return memories

    def forget(self, key: str) -> bool:
        """Delete a memory by key."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM memories WHERE key = ?", (key,))
            return cursor.rowcount > 0

    def list_memories(
        self,
        namespace: str | None = None,
        tags: list[str] | None = None,
        since: datetime | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        """List memories with optional filters."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            sql = "SELECT * FROM memories WHERE 1=1"
            params: list = []

            if namespace:
                sql += " AND namespace = ?"
                params.append(namespace)

            if since:
                sql += " AND created_at >= ?"
                params.append(since.isoformat())

            sql += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)

            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()

            memories = [self._row_to_memory(row) for row in rows]

            if tags:
                memories = [m for m in memories if any(t in m.tags for t in tags)]

            return memories

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        """Convert a database row to a Memory object."""
        return Memory(
            id=row["id"],
            key=row["key"],
            value=row["value"],
            namespace=row["namespace"],
            tags=json.loads(row["tags"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            created_by=row["created_by"],
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            access_count=row["access_count"],
            last_accessed_at=(
                datetime.fromisoformat(row["last_accessed_at"])
                if row["last_accessed_at"]
                else None
            ),
        )
