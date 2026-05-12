"""
Embedding Service — Multi-Agent Financial Complaint Governance Engine

Dual-mode embeddings:
  - Default (USE_OPENAI_EMBEDDINGS=false): BAAI/bge-small-en-v1.5 via sentence-transformers
  - OpenAI mode (USE_OPENAI_EMBEDDINGS=true): text-embedding-3-small
"""

import logging
import os
from typing import List

logger = logging.getLogger(__name__)

_USE_OPENAI = os.getenv("USE_OPENAI_EMBEDDINGS", "false").lower() == "true"
_OPENAI_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
_LOCAL_MODEL_NAME = "BAAI/bge-small-en-v1.5"

# Lazy-loaded singletons
_local_model = None
_openai_client = None


def _get_local_model():
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer
        logger.info(f"Loading local embedding model: {_LOCAL_MODEL_NAME}")
        _local_model = SentenceTransformer(_LOCAL_MODEL_NAME)
        logger.info("Local embedding model loaded.")
    return _local_model


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _openai_client


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

    if _USE_OPENAI:
        return _embed_openai(texts)
    return _embed_local(texts)


def _embed_local(texts: List[str]) -> List[List[float]]:
    """Embed using local sentence-transformers model (BGE-small)."""
    model = _get_local_model()
    # BGE models benefit from a query prefix for retrieval tasks
    prefixed = [f"Represent this financial complaint for retrieval: {t}" for t in texts]
    vectors = model.encode(prefixed, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vectors]


def _embed_openai(texts: List[str]) -> List[List[float]]:
    """Embed using OpenAI API."""
    client = _get_openai_client()
    # OpenAI API accepts up to 2048 texts per call
    results = []
    chunk_size = 100
    for i in range(0, len(texts), chunk_size):
        chunk = texts[i : i + chunk_size]
        response = client.embeddings.create(
            model=_OPENAI_MODEL,
            input=chunk,
        )
        for item in sorted(response.data, key=lambda x: x.index):
            results.append(item.embedding)
    return results


def get_vector_dim() -> int:
    """Returns the dimension of embeddings for collection creation."""
    if _USE_OPENAI:
        return 1536  # text-embedding-3-small
    return 384  # bge-small-en-v1.5


def get_model_name() -> str:
    if _USE_OPENAI:
        return _OPENAI_MODEL
    return _LOCAL_MODEL_NAME
