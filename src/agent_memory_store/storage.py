"""SQLite storage backend for memories."""

import json
import logging
import sqlite3
import struct
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# No longer needed - using X | None syntax
from . import embeddings

logger = logging.getLogger(__name__)


def _serialize_embedding(embedding: list[float]) -> bytes:
    """Serialize embedding to bytes for sqlite-vec."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def _deserialize_embedding(data: bytes) -> list[float]:
    """Deserialize bytes to embedding list."""
    n = len(data) // 4  # 4 bytes per float32
    return list(struct.unpack(f"{n}f", data))


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
    created_by: str | None = None
    expires_at: datetime | None = None
    access_count: int = 0
    last_accessed_at: datetime | None = None


class MemoryStorage:
    """SQLite-backed memory storage with FTS5 and optional semantic search."""

    def __init__(self, db_path: str | Path = "memories.db"):
        self.db_path = Path(db_path)
        self._vec_available = False
        self._embeddings_available = embeddings.is_available()
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            # Try to load sqlite-vec extension
            try:
                import sqlite_vec

                conn.enable_load_extension(True)
                sqlite_vec.load(conn)
                conn.enable_load_extension(False)
                self._vec_available = True
                logger.debug("sqlite-vec extension loaded")
            except Exception as e:
                logger.info(f"sqlite-vec not available: {e}")
                self._vec_available = False

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

            # Create vec0 virtual table for semantic search if sqlite-vec is available
            if self._vec_available:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='memories_vec'"
                )
                if not cursor.fetchone():
                    conn.execute(f"""
                        CREATE VIRTUAL TABLE memories_vec USING vec0(
                            memory_id TEXT PRIMARY KEY,
                            embedding FLOAT[{embeddings.EMBEDDING_DIMENSION}]
                        )
                    """)

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with sqlite-vec loaded if available."""
        conn = sqlite3.connect(self.db_path)
        if self._vec_available:
            try:
                import sqlite_vec

                conn.enable_load_extension(True)
                sqlite_vec.load(conn)
                conn.enable_load_extension(False)
            except Exception:
                pass
        return conn

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

        # Generate embedding if available
        embedding = None
        if self._embeddings_available and self._vec_available:
            # Combine key, value, and tags for embedding
            text_to_embed = f"{key} {value} {' '.join(tags or [])}"
            embedding = embeddings.get_embedding(text_to_embed)

        with self._get_connection() as conn:
            # Check if key already exists to get the existing id
            cursor = conn.execute("SELECT id FROM memories WHERE key = ?", (key,))
            existing = cursor.fetchone()
            existing_id = existing[0] if existing else None

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

            # Store embedding if available
            if embedding is not None and self._vec_available:
                # Use existing id if updating, otherwise use new id
                vec_id = existing_id if existing_id else memory_id
                embedding_bytes = _serialize_embedding(embedding)

                # Delete existing embedding for this memory (if updating)
                if existing_id:
                    conn.execute("DELETE FROM memories_vec WHERE memory_id = ?", (existing_id,))

                conn.execute(
                    "INSERT INTO memories_vec (memory_id, embedding) VALUES (?, ?)",
                    (vec_id, embedding_bytes),
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

    @property
    def semantic_available(self) -> bool:
        """Check if semantic search is available."""
        return self._vec_available and self._embeddings_available

    def search_semantic(
        self,
        query: str,
        namespace: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[tuple[Memory, float]]:
        """Semantic search memories using vector similarity.

        Returns memories with their similarity scores (higher is better).
        Falls back to FTS5 search if semantic search is unavailable.

        Args:
            query: Natural language query.
            namespace: Optional namespace filter.
            tags: Optional tags filter.
            limit: Maximum results to return.

        Returns:
            List of (Memory, score) tuples, sorted by relevance.
        """
        if not self.semantic_available:
            # Fall back to FTS5 search
            logger.info("Semantic search unavailable, falling back to FTS5")
            memories = self.search(query, namespace, tags, limit)
            # Return with dummy scores (FTS5 doesn't expose rank easily in our interface)
            return [(m, 1.0) for m in memories]

        # Generate query embedding
        query_embedding = embeddings.get_embedding(query)
        if query_embedding is None:
            # Fall back to FTS5
            memories = self.search(query, namespace, tags, limit)
            return [(m, 1.0) for m in memories]

        query_bytes = _serialize_embedding(query_embedding)

        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row

            # Query vec table for similar embeddings
            # vec0 uses L2 distance, so smaller is better
            # We'll convert to similarity score (1 / (1 + distance))
            sql = """
                SELECT
                    m.*,
                    v.distance
                FROM memories_vec v
                JOIN memories m ON m.id = v.memory_id
                WHERE v.embedding MATCH ?
                    AND k = ?
            """
            params: list = [query_bytes, limit * 2]  # Fetch extra for filtering

            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()

            results = []
            for row in rows:
                memory = self._row_to_memory(row)

                # Apply namespace filter
                if namespace and memory.namespace != namespace:
                    continue

                # Apply tags filter
                if tags and not any(t in memory.tags for t in tags):
                    continue

                # Convert L2 distance to similarity score
                distance = row["distance"]
                score = 1.0 / (1.0 + distance)

                results.append((memory, score))

                if len(results) >= limit:
                    break

            return results

    def forget(self, key: str) -> bool:
        """Delete a memory by key."""
        with self._get_connection() as conn:
            # Get the memory id first for vec cleanup
            cursor = conn.execute("SELECT id FROM memories WHERE key = ?", (key,))
            row = cursor.fetchone()

            if not row:
                return False

            memory_id = row[0]

            # Delete from memories table (FTS triggers handle memories_fts)
            conn.execute("DELETE FROM memories WHERE key = ?", (key,))

            # Delete from vec table if available
            if self._vec_available:
                conn.execute("DELETE FROM memories_vec WHERE memory_id = ?", (memory_id,))

            return True

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
