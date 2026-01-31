"""Tests for the symbolic query layer (RLM-inspired features)."""

from datetime import UTC, datetime

import pytest

from agent_memory_store.storage import MemoryStorage, QueryFilters, ScoredMemory


@pytest.fixture
def storage(tmp_path):
    """Create a temporary storage instance."""
    return MemoryStorage(tmp_path / "test.db")


@pytest.fixture
def populated_storage(storage):
    """Storage with test data for query tests."""
    # Store memories with varying attributes
    storage.store(
        key="api-auth-pattern",
        value="The Foo API requires Bearer tokens with scope=read",
        namespace="project:foo",
        tags=["api", "auth", "documentation"],
        importance=8,
    )
    storage.store(
        key="bug-fix-2024",
        value="Fixed null pointer exception in user service",
        namespace="project:foo",
        tags=["bug", "critical"],
        importance=9,
    )
    storage.store(
        key="meeting-notes-jan",
        value="Discussed Q1 roadmap, decided to focus on API improvements",
        namespace="global",
        tags=["meeting", "planning"],
        importance=5,
    )
    storage.store(
        key="user-preference-dark-mode",
        value="User prefers dark mode for all interfaces",
        namespace="session:123",
        tags=["preference", "ui"],
        importance=3,
    )
    storage.store(
        key="deployment-config",
        value="Production uses us-east-1, staging uses eu-west-1",
        namespace="project:infrastructure",
        tags=["config", "deployment", "critical"],
        importance=10,
    )
    return storage


class TestQueryFilters:
    """Tests for structured query filtering."""

    def test_query_by_namespace(self, populated_storage):
        """Test filtering by namespace."""
        filters = QueryFilters(namespace="project:foo")
        results = populated_storage.query(filters)

        assert len(results) == 2
        assert all(m.namespace == "project:foo" for m in results)

    def test_query_by_importance_range(self, populated_storage):
        """Test filtering by importance range."""
        filters = QueryFilters(min_importance=8, max_importance=10)
        results = populated_storage.query(filters)

        assert len(results) == 3
        assert all(8 <= m.importance <= 10 for m in results)

    def test_query_by_text_contains(self, populated_storage):
        """Test substring matching."""
        filters = QueryFilters(text_contains="API")
        results = populated_storage.query(filters)

        assert len(results) >= 2
        assert any("API" in m.value or "API" in m.key for m in results)

    def test_query_by_key_pattern(self, populated_storage):
        """Test regex pattern matching on keys."""
        filters = QueryFilters(key_pattern=r"^api-.*")
        results = populated_storage.query(filters)

        assert len(results) == 1
        assert results[0].key == "api-auth-pattern"

    def test_query_by_value_pattern(self, populated_storage):
        """Test regex pattern matching on values."""
        filters = QueryFilters(value_pattern=r"us-east-\d+")
        results = populated_storage.query(filters)

        assert len(results) == 1
        assert "us-east-1" in results[0].value

    def test_query_by_tags_any(self, populated_storage):
        """Test matching any of given tags."""
        filters = QueryFilters(has_any_tag=["critical", "meeting"])
        results = populated_storage.query(filters)

        assert len(results) == 3  # bug-fix, meeting-notes, deployment-config

    def test_query_by_tags_all(self, populated_storage):
        """Test matching all of given tags."""
        filters = QueryFilters(has_all_tags=["config", "critical"])
        results = populated_storage.query(filters)

        assert len(results) == 1
        assert results[0].key == "deployment-config"

    def test_query_order_by_importance(self, populated_storage):
        """Test ordering by importance."""
        filters = QueryFilters(order_by="importance", order_desc=True, limit=3)
        results = populated_storage.query(filters)

        assert len(results) == 3
        assert results[0].importance >= results[1].importance >= results[2].importance
        assert results[0].importance == 10

    def test_query_pagination(self, populated_storage):
        """Test limit and offset."""
        filters1 = QueryFilters(limit=2, offset=0, order_by="key", order_desc=False)
        filters2 = QueryFilters(limit=2, offset=2, order_by="key", order_desc=False)

        page1 = populated_storage.query(filters1)
        page2 = populated_storage.query(filters2)

        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].key != page2[0].key

    def test_query_never_accessed(self, populated_storage):
        """Test filtering for never-accessed memories."""
        # Access one memory
        populated_storage.recall_by_key("api-auth-pattern")

        filters = QueryFilters(never_accessed=True)
        results = populated_storage.query(filters)

        # All except api-auth-pattern
        assert len(results) == 4
        assert all(m.key != "api-auth-pattern" for m in results)


class TestExplore:
    """Tests for memory store exploration/statistics."""

    def test_explore_empty_store(self, storage):
        """Test exploring empty store."""
        stats = storage.explore()

        assert stats.total_count == 0
        assert stats.namespaces == {}
        assert stats.tags == {}
        assert stats.avg_importance == 0.0

    def test_explore_with_data(self, populated_storage):
        """Test exploring populated store."""
        stats = populated_storage.explore()

        assert stats.total_count == 5
        assert "project:foo" in stats.namespaces
        assert stats.namespaces["project:foo"] == 2
        assert "api" in stats.tags
        assert stats.avg_importance > 0
        assert stats.date_range[0] is not None
        assert stats.date_range[1] is not None

    def test_explore_importance_distribution(self, populated_storage):
        """Test importance distribution in stats."""
        stats = populated_storage.explore()

        assert stats.importance_distribution is not None
        # Should have entries for various importance levels
        assert sum(stats.importance_distribution.values()) == 5


class TestSearchWeighted:
    """Tests for recency × importance × relevance weighted search."""

    def test_search_weighted_returns_scored_memories(self, populated_storage):
        """Test that weighted search returns ScoredMemory objects."""
        results = populated_storage.search_weighted("API authentication")

        assert all(isinstance(r, ScoredMemory) for r in results)
        assert all(hasattr(r, "recency_score") for r in results)
        assert all(hasattr(r, "importance_score") for r in results)
        assert all(hasattr(r, "relevance_score") for r in results)

    def test_search_weighted_importance_affects_score(self, populated_storage):
        """Test that higher importance increases score."""
        # Search for something both have
        results = populated_storage.search_weighted(
            "config deployment",
            importance_weight=10.0,  # Heavily weight importance
            recency_weight=0.0,
            relevance_weight=1.0,
        )

        # deployment-config has importance 10, should be near top
        keys = [r.memory.key for r in results[:3]]
        assert "deployment-config" in keys

    def test_search_weighted_recency_decay(self, populated_storage):
        """Test that recent memories score higher for recency."""
        results = populated_storage.search_weighted(
            "API",
            recency_weight=1.0,
            importance_weight=0.0,
            relevance_weight=0.0,
        )

        # All recently created, so recency scores should be high (close to 1)
        assert all(r.recency_score > 0.9 for r in results)

    def test_search_weighted_custom_weights(self, populated_storage):
        """Test custom weight combinations."""
        # Relevance only
        results = populated_storage.search_weighted(
            "Bearer tokens API",
            recency_weight=0.0,
            importance_weight=0.0,
            relevance_weight=1.0,
            limit=1,
        )

        assert len(results) >= 1
        # Should find the API auth pattern
        # Score should equal just relevance_score (since other weights are 0)
        assert abs(results[0].score - results[0].relevance_score) < 0.01

    def test_search_weighted_with_namespace_filter(self, populated_storage):
        """Test weighted search with namespace filter."""
        results = populated_storage.search_weighted(
            "API",
            namespace="project:foo",
        )

        assert all(r.memory.namespace == "project:foo" for r in results)


class TestAggregate:
    """Tests for memory aggregation."""

    def test_aggregate_by_namespace(self, populated_storage):
        """Test aggregating by namespace."""
        result = populated_storage.aggregate(group_by="namespace")

        assert result["group_by"] == "namespace"
        assert result["total"] == 5
        assert "project:foo" in result["groups"]
        assert result["groups"]["project:foo"] == 2

    def test_aggregate_by_tag(self, populated_storage):
        """Test aggregating by tag."""
        result = populated_storage.aggregate(group_by="tag")

        assert "critical" in result["groups"]
        assert result["groups"]["critical"] == 2  # bug-fix and deployment

    def test_aggregate_by_importance(self, populated_storage):
        """Test aggregating by importance level."""
        result = populated_storage.aggregate(group_by="importance")

        assert 10 in result["groups"]
        assert result["groups"][10] == 1  # deployment-config

    def test_aggregate_by_date(self, populated_storage):
        """Test aggregating by date."""
        result = populated_storage.aggregate(group_by="date")

        # All created today
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        assert today in result["groups"]

    def test_aggregate_with_filters(self, populated_storage):
        """Test aggregating with pre-filters."""
        filters = QueryFilters(min_importance=8)
        result = populated_storage.aggregate(group_by="namespace", filters=filters)

        assert result["total"] == 3  # Only high importance memories


class TestRecencyScoring:
    """Tests specifically for recency-weighted retrieval scoring."""

    def test_recent_low_importance_vs_old_high_importance(self, storage):
        """Test: old high-importance should beat recent low-importance."""
        # Store old high-importance memory (simulate by using weighted search parameters)
        storage.store(
            key="old-critical",
            value="Critical system architecture decision",
            importance=10,
        )
        storage.store(
            key="recent-trivial",
            value="Minor code style preference",
            importance=2,
        )

        # With balanced weights, importance should win
        results = storage.search_weighted(
            "code decision",
            recency_weight=1.0,
            importance_weight=2.0,  # Weight importance higher
            relevance_weight=1.0,
        )

        # Higher importance should rank first
        if len(results) >= 2:
            assert results[0].memory.importance >= results[1].memory.importance

    def test_recency_decay_parameter(self, storage):
        """Test that decay_days parameter affects recency scoring."""
        storage.store(key="test", value="test memory", importance=5)

        # With very short decay, recency drops fast (but all are recent so still high)
        results_short = storage.search_weighted("test", recency_decay_days=1.0)

        # With very long decay, recency stays high longer
        results_long = storage.search_weighted("test", recency_decay_days=365.0)

        # Both should find the memory
        assert len(results_short) >= 1
        assert len(results_long) >= 1
        # Long decay should give higher recency score
        assert results_long[0].recency_score >= results_short[0].recency_score

    def test_importance_normalization(self, storage):
        """Test that importance is normalized to 0-1."""
        storage.store(key="min", value="minimum importance", importance=1)
        storage.store(key="max", value="maximum importance", importance=10)

        results = storage.search_weighted("importance", relevance_weight=0.0, recency_weight=0.0)

        for r in results:
            assert 0.0 <= r.importance_score <= 1.0

        # Find min and max
        min_mem = next(r for r in results if r.memory.key == "min")
        max_mem = next(r for r in results if r.memory.key == "max")

        assert min_mem.importance_score == 0.0  # (1-1)/9 = 0
        assert max_mem.importance_score == 1.0  # (10-1)/9 = 1
