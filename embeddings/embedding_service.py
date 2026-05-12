"""
Embedding Service — Multi-Agent Financial Complaint Governance Engine

Local embeddings:
  - BAAI/bge-small-en-v1.5 via sentence-transformers
"""

import logging
from typing import List

logger = logging.getLogger(__name__)

_LOCAL_MODEL_NAME = "BAAI/bge-small-en-v1.5"

# Lazy-loaded singleton
_local_model = None


def _get_local_model():
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer
        logger.info(f"Loading local embedding model: {_LOCAL_MODEL_NAME}")
        _local_model = SentenceTransformer(_LOCAL_MODEL_NAME)
        logger.info("Local embedding model loaded.")
    return _local_model


def embed_text(text: str) -> List[float]:
    """Embed a single string. Returns a list of floats."""
    texts = embed_batch([text])
    return texts[0]


def embed_batch(texts: List[str]) -> List[List[float]]:
    """
    Embed a batch of strings.
    Returns list of embedding vectors, one per input text.
    """
    if not texts:
        return []

    return _embed_local(texts)


def _embed_local(texts: List[str]) -> List[List[float]]:
    """Embed using local sentence-transformers model (BGE-small)."""
    model = _get_local_model()
    # BGE models benefit from a query prefix for retrieval tasks
    prefixed = [f"Represent this financial complaint for retrieval: {t}" for t in texts]
    vectors = model.encode(prefixed, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vectors]


def get_vector_dim() -> int:
    """Returns the dimension of embeddings for collection creation."""
    return 384  # bge-small-en-v1.5


def get_model_name() -> str:
    return _LOCAL_MODEL_NAME
