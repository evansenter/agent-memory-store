"""SQLite storage backend for memories."""

import json
import logging
import re
import sqlite3
import struct
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

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
    importance: int = 5  # 1-10 scale, default 5 (medium)


@dataclass
class QueryFilters:
    """Structured query filters for symbolic memory access."""

    # Text filters
    key_pattern: str | None = None  # Regex pattern for key
    value_pattern: str | None = None  # Regex pattern for value
    text_contains: str | None = None  # Substring match in key or value

    # Date filters
    created_after: datetime | None = None
    created_before: datetime | None = None
    updated_after: datetime | None = None
    updated_before: datetime | None = None

    # Importance filter
    min_importance: int | None = None
    max_importance: int | None = None

    # Standard filters
    namespace: str | None = None
    tags: list[str] | None = None
    has_any_tag: list[str] | None = None  # Match any of these tags
    has_all_tags: list[str] | None = None  # Match all of these tags

    # Access patterns
    min_access_count: int | None = None
    accessed_after: datetime | None = None
    never_accessed: bool = False

    # Pagination
    limit: int = 50
    offset: int = 0

    # Sorting
    order_by: Literal["created_at", "updated_at", "importance", "access_count", "key"] = "updated_at"
    order_desc: bool = True


@dataclass
class MemoryStats:
    """Statistics about the memory store."""

    total_count: int
    namespaces: dict[str, int]  # namespace -> count
    tags: dict[str, int]  # tag -> count
    importance_distribution: dict[int, int]  # importance level -> count
    date_range: tuple[datetime | None, datetime | None]  # (oldest, newest)
    avg_importance: float
    total_access_count: int
    semantic_available: bool


@dataclass
class ScoredMemory:
    """A memory with a composite retrieval score."""

    memory: Memory
    score: float
    recency_score: float = 0.0
    importance_score: float = 0.0
    relevance_score: float = 0.0


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
                    last_accessed_at TEXT,
                    importance INTEGER DEFAULT 5
                );

                CREATE INDEX IF NOT EXISTS idx_memories_namespace ON memories(namespace);
                CREATE INDEX IF NOT EXISTS idx_memories_expires ON memories(expires_at);
            """)
            
            # Migration: Add importance column if it doesn't exist
            cursor = conn.execute("PRAGMA table_info(memories)")
            columns = [row[1] for row in cursor.fetchall()]
            if "importance" not in columns:
                conn.execute("ALTER TABLE memories ADD COLUMN importance INTEGER DEFAULT 5")
            
            # Create importance index (after migration ensures column exists)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance)")

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
        importance: int = 5,
    ) -> Memory:
        """Store a memory, replacing if key exists.
        
        Args:
            importance: 1-10 scale (1=trivial, 5=normal, 10=critical)
        """
        memory_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        tags_json = json.dumps(tags or [])
        expires_at = None
        importance = max(1, min(10, importance))  # Clamp to 1-10
        if ttl_days:

            expires_at = (datetime.now(UTC) + timedelta(days=ttl_days)).isoformat()

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
                INSERT INTO memories (id, key, value, namespace, tags, created_at, updated_at, created_by, expires_at, importance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    namespace = excluded.namespace,
                    tags = excluded.tags,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at,
                    importance = excluded.importance
                """,
                (memory_id, key, value, namespace, tags_json, now, now, created_by, expires_at, importance),
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
            importance=importance,
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
                (datetime.now(UTC).isoformat(), key),
            )

            return self._row_to_memory(row)

    def _escape_fts5_query(self, query: str) -> str:
        """Escape a query string for FTS5 MATCH.
        
        FTS5 interprets hyphens, colons, etc. as operators. We escape by
        double-quoting each word to treat them as literals.
        """
        # Split on whitespace and quote each term
        terms = query.split()
        escaped = " ".join(f'"{term}"' for term in terms)
        return escaped

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

            # Escape the query for FTS5
            escaped_query = self._escape_fts5_query(query)

            # Build query with optional filters
            sql = """
                SELECT m.* FROM memories m
                JOIN memories_fts fts ON m.rowid = fts.rowid
                WHERE memories_fts MATCH ?
            """
            params: list = [escaped_query]

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
            importance=row["importance"] if "importance" in row.keys() else 5,
        )

    # =========================================================================
    # Symbolic Query Layer (RLM-inspired)
    # =========================================================================

    def query(self, filters: QueryFilters) -> list[Memory]:
        """Execute a structured query with symbolic filters.
        
        This enables code-based filtering before semantic search,
        allowing agents to programmatically explore memories.
        
        Args:
            filters: QueryFilters specifying constraints.
            
        Returns:
            List of matching memories.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            sql = "SELECT * FROM memories WHERE 1=1"
            params: list = []

            # Namespace filter
            if filters.namespace:
                sql += " AND namespace = ?"
                params.append(filters.namespace)

            # Date filters
            if filters.created_after:
                sql += " AND created_at >= ?"
                params.append(filters.created_after.isoformat())
            if filters.created_before:
                sql += " AND created_at <= ?"
                params.append(filters.created_before.isoformat())
            if filters.updated_after:
                sql += " AND updated_at >= ?"
                params.append(filters.updated_after.isoformat())
            if filters.updated_before:
                sql += " AND updated_at <= ?"
                params.append(filters.updated_before.isoformat())

            # Importance filters
            if filters.min_importance is not None:
                sql += " AND importance >= ?"
                params.append(filters.min_importance)
            if filters.max_importance is not None:
                sql += " AND importance <= ?"
                params.append(filters.max_importance)

            # Access pattern filters
            if filters.min_access_count is not None:
                sql += " AND access_count >= ?"
                params.append(filters.min_access_count)
            if filters.accessed_after:
                sql += " AND last_accessed_at >= ?"
                params.append(filters.accessed_after.isoformat())
            if filters.never_accessed:
                sql += " AND last_accessed_at IS NULL"

            # Text contains (substring match in SQL)
            if filters.text_contains:
                sql += " AND (key LIKE ? OR value LIKE ?)"
                pattern = f"%{filters.text_contains}%"
                params.extend([pattern, pattern])

            # Sorting
            order_col = filters.order_by
            order_dir = "DESC" if filters.order_desc else "ASC"
            sql += f" ORDER BY {order_col} {order_dir}"

            # Pagination
            sql += " LIMIT ? OFFSET ?"
            params.extend([filters.limit, filters.offset])

            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()

            memories = [self._row_to_memory(row) for row in rows]

            # Apply regex filters in Python (SQLite regex is limited)
            if filters.key_pattern:
                pattern = re.compile(filters.key_pattern, re.IGNORECASE)
                memories = [m for m in memories if pattern.search(m.key)]
            if filters.value_pattern:
                pattern = re.compile(filters.value_pattern, re.IGNORECASE)
                memories = [m for m in memories if pattern.search(m.value)]

            # Apply tag filters in Python
            if filters.tags:  # Legacy: any of these tags
                memories = [m for m in memories if any(t in m.tags for t in filters.tags)]
            if filters.has_any_tag:
                memories = [m for m in memories if any(t in m.tags for t in filters.has_any_tag)]
            if filters.has_all_tags:
                memories = [m for m in memories if all(t in m.tags for t in filters.has_all_tags)]

            return memories

    def explore(self) -> MemoryStats:
        """Get statistics about the memory store.
        
        Useful for agents to understand what's available before querying.
        
        Returns:
            MemoryStats with counts, distributions, and metadata.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Total count
            total = conn.execute("SELECT COUNT(*) as cnt FROM memories").fetchone()["cnt"]

            # Namespace distribution
            namespaces = {}
            for row in conn.execute(
                "SELECT namespace, COUNT(*) as cnt FROM memories GROUP BY namespace"
            ):
                namespaces[row["namespace"]] = row["cnt"]

            # Tag distribution (requires parsing JSON)
            tags: dict[str, int] = {}
            for row in conn.execute("SELECT tags FROM memories"):
                for tag in json.loads(row["tags"]):
                    tags[tag] = tags.get(tag, 0) + 1

            # Importance distribution
            importance_dist = {}
            for row in conn.execute(
                "SELECT importance, COUNT(*) as cnt FROM memories GROUP BY importance"
            ):
                importance_dist[row["importance"]] = row["cnt"]

            # Date range
            date_row = conn.execute(
                "SELECT MIN(created_at) as oldest, MAX(created_at) as newest FROM memories"
            ).fetchone()
            oldest = datetime.fromisoformat(date_row["oldest"]) if date_row["oldest"] else None
            newest = datetime.fromisoformat(date_row["newest"]) if date_row["newest"] else None

            # Average importance
            avg_row = conn.execute("SELECT AVG(importance) as avg_imp FROM memories").fetchone()
            avg_importance = avg_row["avg_imp"] or 0.0

            # Total access count
            access_row = conn.execute(
                "SELECT SUM(access_count) as total FROM memories"
            ).fetchone()
            total_access = access_row["total"] or 0

            return MemoryStats(
                total_count=total,
                namespaces=namespaces,
                tags=dict(sorted(tags.items(), key=lambda x: -x[1])[:50]),  # Top 50 tags
                importance_distribution=importance_dist,
                date_range=(oldest, newest),
                avg_importance=round(avg_importance, 2),
                total_access_count=total_access,
                semantic_available=self.semantic_available,
            )

    def search_weighted(
        self,
        query: str,
        namespace: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
        recency_weight: float = 1.0,
        importance_weight: float = 1.0,
        relevance_weight: float = 1.0,
        recency_decay_days: float = 30.0,
    ) -> list[ScoredMemory]:
        """Search with combined recency × importance × relevance scoring.
        
        Implements the Generative Agents retrieval model where memories
        are scored by a weighted combination of:
        - Recency: How recently the memory was created/updated
        - Importance: The stored importance value (1-10)
        - Relevance: Semantic similarity to the query
        
        Args:
            query: Search query for relevance scoring.
            namespace: Optional namespace filter.
            tags: Optional tag filter.
            limit: Maximum results to return.
            recency_weight: Weight for recency component (default 1.0).
            importance_weight: Weight for importance component (default 1.0).
            relevance_weight: Weight for relevance component (default 1.0).
            recency_decay_days: Days until recency score decays to ~0.37 (default 30).
            
        Returns:
            List of ScoredMemory with component scores.
        """
        # Get semantic search results with relevance scores
        if self.semantic_available:
            results = self.search_semantic(query, namespace, tags, limit=limit * 3)
        else:
            # Fall back to FTS with uniform relevance
            memories = self.search(query, namespace, tags, limit=limit * 3)
            results = [(m, 1.0) for m in memories]

        now = datetime.now(UTC)
        scored: list[ScoredMemory] = []

        for memory, relevance in results:
            # Recency score: exponential decay from updated_at
            # score = exp(-days_old / decay_days)
            days_old = (now - memory.updated_at).total_seconds() / 86400
            recency = 2.71828 ** (-days_old / recency_decay_days)

            # Importance score: normalize to 0-1 (importance is 1-10)
            importance = (memory.importance - 1) / 9.0

            # Relevance is already 0-1 from semantic search

            # Combined score
            total = (
                recency_weight * recency
                + importance_weight * importance
                + relevance_weight * relevance
            )

            scored.append(
                ScoredMemory(
                    memory=memory,
                    score=total,
                    recency_score=recency,
                    importance_score=importance,
                    relevance_score=relevance,
                )
            )

        # Sort by combined score, return top N
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:limit]

    def aggregate(
        self,
        group_by: Literal["namespace", "tag", "importance", "date"] = "namespace",
        filters: QueryFilters | None = None,
    ) -> dict:
        """Aggregate memories by a dimension.
        
        Useful for understanding memory distribution without loading all data.
        
        Args:
            group_by: Dimension to group by.
            filters: Optional filters to apply before aggregating.
            
        Returns:
            Dict with aggregation results.
        """
        # First apply filters to get the subset
        if filters:
            memories = self.query(filters)
        else:
            # Get all memories
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM memories")
                memories = [self._row_to_memory(row) for row in cursor.fetchall()]

        result: dict = {"group_by": group_by, "groups": {}, "total": len(memories)}

        if group_by == "namespace":
            groups: dict[str, int] = {}
            for m in memories:
                groups[m.namespace] = groups.get(m.namespace, 0) + 1
            result["groups"] = groups

        elif group_by == "tag":
            groups = {}
            for m in memories:
                for tag in m.tags:
                    groups[tag] = groups.get(tag, 0) + 1
            result["groups"] = dict(sorted(groups.items(), key=lambda x: -x[1]))

        elif group_by == "importance":
            groups = {}
            for m in memories:
                groups[m.importance] = groups.get(m.importance, 0) + 1
            result["groups"] = groups

        elif group_by == "date":
            # Group by date (YYYY-MM-DD)
            groups = {}
            for m in memories:
                date_key = m.created_at.strftime("%Y-%m-%d")
                groups[date_key] = groups.get(date_key, 0) + 1
            result["groups"] = dict(sorted(groups.items()))

        return result
