"""Embeddings module for semantic search.

Uses sentence-transformers with all-MiniLM-L6-v2 model (~80MB).
Gracefully degrades if sentence-transformers is not installed.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Lazy-loaded model instance
_model = None  # SentenceTransformer | None
_embeddings_available: bool | None = None

# Model configuration
MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384  # Output dimension for all-MiniLM-L6-v2


def is_available() -> bool:
    """Check if embeddings are available (sentence-transformers installed)."""
    global _embeddings_available
    if _embeddings_available is None:
        try:
            import sentence_transformers  # noqa: F401

            _embeddings_available = True
        except ImportError:
            _embeddings_available = False
            logger.info(
                "sentence-transformers not installed. "
                "Semantic search unavailable. "
                "Install with: pip install agent-memory-store[embeddings]"
            )
    return _embeddings_available


def _get_model():
    """Lazily load the sentence-transformers model."""
    global _model
    if _model is None and is_available():
        try:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading embedding model: {MODEL_NAME}")
            _model = SentenceTransformer(MODEL_NAME)
            logger.info("Embedding model loaded successfully")
        except Exception as e:
            logger.warning(f"Failed to load embedding model: {e}")
            return None
    return _model


def get_embedding(text: str) -> list[float] | None:
    """Generate an embedding vector for the given text.

    Args:
        text: The text to embed.

    Returns:
        A list of floats representing the embedding vector,
        or None if embeddings are not available.
    """
    model = _get_model()
    if model is None:
        return None

    try:
        # Encode returns numpy array, convert to list
        embedding = model.encode(text, convert_to_numpy=True)
        return embedding.tolist()
    except Exception as e:
        logger.warning(f"Failed to generate embedding: {e}")
        return None


def get_embeddings_batch(texts: list[str]) -> list[list[float]] | None:
    """Generate embedding vectors for multiple texts.

    More efficient than calling get_embedding repeatedly.

    Args:
        texts: List of texts to embed.

    Returns:
        A list of embedding vectors, or None if embeddings are not available.
    """
    model = _get_model()
    if model is None:
        return None

    try:
        embeddings = model.encode(texts, convert_to_numpy=True)
        return [e.tolist() for e in embeddings]
    except Exception as e:
        logger.warning(f"Failed to generate embeddings batch: {e}")
        return None
