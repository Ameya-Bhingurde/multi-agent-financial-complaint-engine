"""
Qdrant Vector Store — Multi-Agent Financial Complaint Governance Engine

Manages the Qdrant collection: creation, batched upsert, and
metadata-filtered approximate nearest neighbour search.
"""

import logging
import os
import uuid
from typing import Any, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

logger = logging.getLogger(__name__)

_QDRANT_HOST       = os.getenv("QDRANT_HOST", "localhost")
_QDRANT_PORT       = int(os.getenv("QDRANT_PORT", "6333"))
_COLLECTION_NAME   = os.getenv("QDRANT_COLLECTION", "cfpb_pages")

_client: Optional[QdrantClient] = None


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(host=_QDRANT_HOST, port=_QDRANT_PORT, timeout=30)
        logger.info(f"Qdrant client connected → {_QDRANT_HOST}:{_QDRANT_PORT}")
    return _client


def create_collection(vector_dim: int, recreate: bool = False) -> None:
    """
    Idempotently create the Qdrant collection.
    Set recreate=True only when you want to wipe and rebuild from scratch.
    """
    client = get_client()
    existing = [c.name for c in client.get_collections().collections]

    if _COLLECTION_NAME in existing:
        if recreate:
            client.delete_collection(_COLLECTION_NAME)
            logger.warning(f"Deleted existing collection: {_COLLECTION_NAME}")
        else:
            logger.info(f"Collection '{_COLLECTION_NAME}' already exists — skipping creation.")
            return

    client.create_collection(
        collection_name=_COLLECTION_NAME,
        vectors_config=qmodels.VectorParams(
            size=vector_dim,
            distance=qmodels.Distance.COSINE,
        ),
        # Enable payload indexing for fast metadata filtering
        on_disk_payload=True,
    )

    # Create payload indexes for fast filtering
    for field, schema_type in [
        ("product",      qmodels.PayloadSchemaType.KEYWORD),
        ("issue",        qmodels.PayloadSchemaType.KEYWORD),
        ("section_type", qmodels.PayloadSchemaType.KEYWORD),
        ("complaint_id", qmodels.PayloadSchemaType.KEYWORD),
    ]:
        client.create_payload_index(
            collection_name=_COLLECTION_NAME,
            field_name=field,
            field_schema=schema_type,
        )

    logger.info(f"Collection '{_COLLECTION_NAME}' created with dim={vector_dim} and payload indexes.")


def upsert_vectors(points: list[dict]) -> None:
    """
    Upsert a list of vector points into Qdrant.

    Each point dict must have:
      - id         : str (UUID)
      - vector     : List[float]
      - payload    : dict  {complaint_id, section_type, product, issue, page_num,
                            resolution, text_snippet}
    """
    if not points:
        return

    client = get_client()
    qdrant_points = [
        qmodels.PointStruct(
            id=str(p["id"]),
            vector=p["vector"],
            payload=p["payload"],
        )
        for p in points
    ]

    BATCH = 64
    for i in range(0, len(qdrant_points), BATCH):
        chunk = qdrant_points[i : i + BATCH]
        client.upsert(collection_name=_COLLECTION_NAME, points=chunk, wait=True)

    logger.debug(f"Upserted {len(points)} vectors into '{_COLLECTION_NAME}'.")


def search(
    query_vector: list[float],
    top_k: int = 5,
    product_filter: Optional[str] = None,
    issue_filter: Optional[str] = None,
    section_filter: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Metadata-filtered ANN search.

    Returns list of dicts:
      {id, score, payload}
    """
    client = get_client()

    must_conditions = []
    if product_filter:
        must_conditions.append(
            qmodels.FieldCondition(
                key="product",
                match=qmodels.MatchText(text=product_filter),
            )
        )
    if issue_filter:
        must_conditions.append(
            qmodels.FieldCondition(
                key="issue",
                match=qmodels.MatchText(text=issue_filter),
            )
        )
    if section_filter:
        must_conditions.append(
            qmodels.FieldCondition(
                key="section_type",
                match=qmodels.MatchValue(value=section_filter),
            )
        )

    query_filter = qmodels.Filter(must=must_conditions) if must_conditions else None

    results = client.search(
        collection_name=_COLLECTION_NAME,
        query_vector=query_vector,
        limit=top_k,
        query_filter=query_filter,
        with_payload=True,
    )

    return [
        {
            "id":      str(hit.id),
            "score":   hit.score,
            "payload": hit.payload,
        }
        for hit in results
    ]


def get_collection_info() -> dict:
    """Returns basic stats about the collection."""
    client = get_client()
    info = client.get_collection(_COLLECTION_NAME)
    return {
        "vectors_count":  info.vectors_count,
        "points_count":   info.points_count,
        "status":         str(info.status),
    }


def health_check() -> bool:
    """Returns True if Qdrant is reachable."""
    try:
        get_client().get_collections()
        return True
    except Exception:
        return False
