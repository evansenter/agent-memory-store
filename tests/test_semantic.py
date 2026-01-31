"""Tests for semantic search functionality."""

import pytest

from agent_memory_store import embeddings
from agent_memory_store.storage import MemoryStorage


class TestEmbeddingsModule:
    """Tests for the embeddings module."""

    def test_is_available_returns_bool(self):
        """Test that is_available returns a boolean."""
        result = embeddings.is_available()
        assert isinstance(result, bool)

    def test_embedding_dimension_constant(self):
        """Test that EMBEDDING_DIMENSION is defined correctly."""
        assert embeddings.EMBEDDING_DIMENSION == 384

    def test_get_embedding_without_library(self):
        """Test get_embedding when sentence-transformers is not installed."""
        # This test works regardless of whether the library is installed
        # since we're testing the interface
        result = embeddings.get_embedding("test text")
        if embeddings.is_available():
            assert isinstance(result, list)
            assert len(result) == embeddings.EMBEDDING_DIMENSION
            assert all(isinstance(x, float) for x in result)
        else:
            assert result is None

    def test_get_embeddings_batch(self):
        """Test batch embedding generation."""
        texts = ["hello world", "goodbye world"]
        result = embeddings.get_embeddings_batch(texts)

        if embeddings.is_available():
            assert isinstance(result, list)
            assert len(result) == 2
            assert all(len(e) == embeddings.EMBEDDING_DIMENSION for e in result)
        else:
            assert result is None


class TestSemanticSearchAvailability:
    """Tests for semantic search availability detection."""

    def test_semantic_available_property(self, storage):
        """Test that semantic_available property works."""
        result = storage.semantic_available
        assert isinstance(result, bool)

    def test_semantic_search_fallback(self, storage):
        """Test that semantic search falls back to FTS when unavailable."""
        # Store some test data
        storage.store(key="doc1", value="Python programming language")
        storage.store(key="doc2", value="JavaScript web development")

        # This should work regardless of whether semantic is available
        results = storage.search_semantic("programming")

        assert isinstance(results, list)
        # Results are (Memory, score) tuples
        if results:
            memory, score = results[0]
            assert hasattr(memory, "key")
            assert hasattr(memory, "value")
            assert isinstance(score, float)


@pytest.mark.skipif(not embeddings.is_available(), reason="sentence-transformers not installed")
class TestSemanticSearchWithEmbeddings:
    """Tests that require sentence-transformers to be installed."""

    def test_embedding_generation(self):
        """Test that embeddings are generated correctly."""
        text = "The quick brown fox jumps over the lazy dog"
        embedding = embeddings.get_embedding(text)

        assert embedding is not None
        assert len(embedding) == 384
        assert all(isinstance(x, float) for x in embedding)

    def test_similar_texts_have_similar_embeddings(self):
        """Test that semantically similar texts have similar embeddings."""
        import math

        text1 = "I love programming in Python"
        text2 = "Python programming is great"
        text3 = "The weather is sunny today"

        emb1 = embeddings.get_embedding(text1)
        emb2 = embeddings.get_embedding(text2)
        emb3 = embeddings.get_embedding(text3)

        # Cosine similarity helper
        def cosine_sim(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x * x for x in a))
            norm_b = math.sqrt(sum(x * x for x in b))
            return dot / (norm_a * norm_b)

        sim_1_2 = cosine_sim(emb1, emb2)
        sim_1_3 = cosine_sim(emb1, emb3)

        # Similar texts should have higher similarity
        assert sim_1_2 > sim_1_3

    def test_semantic_search_finds_related_content(self, semantic_storage):
        """Test that semantic search finds semantically related content."""
        # Store memories with different content
        semantic_storage.store(
            key="python-intro",
            value="Python is a high-level programming language known for readability",
        )
        semantic_storage.store(
            key="js-intro", value="JavaScript is used for web development and runs in browsers"
        )
        semantic_storage.store(
            key="cooking-tips", value="To make a great pasta, boil water with salt first"
        )

        # Search for something related to programming
        results = semantic_storage.search_semantic("coding languages")

        assert len(results) > 0
        # Programming-related memories should rank higher than cooking
        keys = [m.key for m, score in results]
        assert "cooking-tips" not in keys[:2]  # Should not be in top 2

    def test_semantic_search_with_namespace_filter(self, semantic_storage):
        """Test semantic search respects namespace filter."""
        semantic_storage.store(
            key="proj-a-doc", value="Machine learning model training", namespace="project:a"
        )
        semantic_storage.store(
            key="proj-b-doc", value="Machine learning inference", namespace="project:b"
        )

        results = semantic_storage.search_semantic("ML models", namespace="project:a")

        assert len(results) == 1
        assert results[0][0].key == "proj-a-doc"

    def test_semantic_search_with_tags_filter(self, semantic_storage):
        """Test semantic search respects tags filter."""
        semantic_storage.store(
            key="urgent-task", value="Complete the API documentation", tags=["urgent", "docs"]
        )
        semantic_storage.store(key="normal-task", value="Write API examples", tags=["docs"])

        results = semantic_storage.search_semantic("documentation", tags=["urgent"])

        assert len(results) == 1
        assert results[0][0].key == "urgent-task"

    def test_semantic_search_returns_scores(self, semantic_storage):
        """Test that semantic search returns valid similarity scores."""
        semantic_storage.store(key="test-doc", value="Test document content")

        results = semantic_storage.search_semantic("test document")

        assert len(results) > 0
        memory, score = results[0]
        assert 0 < score <= 1.0  # Similarity score should be between 0 and 1

    def test_embedding_update_on_memory_update(self, semantic_storage):
        """Test that embeddings are updated when a memory is updated."""
        # Store initial memory
        semantic_storage.store(key="evolving", value="I love cats and kittens")

        # Search should find it with cat-related query
        results1 = semantic_storage.search_semantic("feline pets")
        assert any(m.key == "evolving" for m, _ in results1)

        # Update the memory to be about something completely different
        semantic_storage.store(key="evolving", value="Quantum computing uses qubits")

        # Now it should match quantum-related queries better
        results2 = semantic_storage.search_semantic("quantum physics")
        assert any(m.key == "evolving" for m, _ in results2)

    def test_embedding_deleted_with_memory(self, semantic_storage):
        """Test that embeddings are deleted when memory is deleted."""
        semantic_storage.store(key="temporary", value="This will be deleted soon")

        # Verify it's searchable
        results1 = semantic_storage.search_semantic("deleted")
        assert any(m.key == "temporary" for m, _ in results1)

        # Delete the memory
        semantic_storage.forget("temporary")

        # Should no longer be in results
        results2 = semantic_storage.search_semantic("deleted")
        assert not any(m.key == "temporary" for m, _ in results2)


@pytest.fixture
def semantic_storage(temp_db):
    """Create a MemoryStorage instance configured for semantic search."""
    storage = MemoryStorage(temp_db)
    if not storage.semantic_available:
        pytest.skip("Semantic search not available (sqlite-vec or embeddings missing)")
    return storage
