"""
PageIndex Retriever — Multi-Agent Financial Complaint Governance Engine

Implements hierarchical retrieval:
  1. Embed the incoming complaint text
  2. Query Qdrant with metadata filters (product + issue)
  3. Fetch top-K page segments
  4. Group segments by complaint_id
  5. Reconstruct a ranked, hierarchical context structure
"""

import logging
import os
from collections import defaultdict
from typing import Any, Optional

from embeddings.embedding_service import embed_text
from embeddings.qdrant_store import search

logger = logging.getLogger(__name__)

DEFAULT_TOP_K       = int(os.getenv("RETRIEVAL_TOP_K", "5"))
MIN_SIMILAR_CASES   = int(os.getenv("MIN_SIMILAR_CASES", "5"))


def retrieve_similar_cases(
    complaint_text: str,
    product: Optional[str]       = None,
    issue: Optional[str]         = None,
    top_k: int                   = DEFAULT_TOP_K,
    section_filter: Optional[str]= "narrative",
) -> dict[str, Any]:
    """
    Retrieve the most similar past complaint cases for a given complaint text.

    Returns:
    {
        "cases":          List of ranked complaint groups,
        "cold_start":     True if fewer than MIN_SIMILAR_CASES found,
        "total_found":    int
    }
    """
    # Step 1 — Embed the incoming query
    query_vector = embed_text(complaint_text)

    # Step 2 — Metadata-filtered Qdrant search
    hits = search(
        query_vector    = query_vector,
        top_k           = top_k * 3,   # over-fetch to allow grouping
        product_filter  = product,
        issue_filter    = None,         # issue strings vary too much for exact match
        section_filter  = section_filter,
    )

    # Step 3 — Group hits by complaint_id
    groups: dict[str, dict] = defaultdict(lambda: {
        "complaint_id":     "",
        "segments":         [],
        "max_score":        0.0,
        "product":          "",
        "issue":            "",
        "resolution":       "",
        "disputed":         False,
    })

    for hit in hits:
        cid = hit["payload"].get("complaint_id", "")
        if not cid:
            continue
        g = groups[cid]
        g["complaint_id"]  = cid
        g["product"]       = hit["payload"].get("product", "")
        g["issue"]         = hit["payload"].get("issue", "")
        g["resolution"]    = hit["payload"].get("company_response", "")
        g["disputed"]      = hit["payload"].get("disputed", False)
        g["max_score"]     = max(g["max_score"], hit["score"])
        g["segments"].append({
            "page_num":     hit["payload"].get("page_num"),
            "section_type": hit["payload"].get("section_type"),
            "text_snippet": hit["payload"].get("text_snippet", ""),
            "similarity":   round(hit["score"], 4),
        })

    # Step 4 — Sort groups by max similarity, take top_k
    ranked = sorted(groups.values(), key=lambda x: x["max_score"], reverse=True)[:top_k]

    cold_start = len(ranked) < MIN_SIMILAR_CASES

    return {
        "cases":        ranked,
        "cold_start":   cold_start,
        "total_found":  len(ranked),
    }


def get_historical_relief_rate(
    product: Optional[str] = None,
    issue: Optional[str]   = None,
    sample_size: int        = 50,
) -> float:
    """
    Estimate historical monetary relief rate from the vector store payload data.
    Queries a broad sample and counts 'monetary relief' responses.
    Falls back to 0.5 on cold start.
    """
    try:
        from embeddings.qdrant_store import get_client, _COLLECTION_NAME
        from qdrant_client.http import models as qmodels

        client = get_client()
        # Scroll through sample records to compute rate
        records, _ = client.scroll(
            collection_name = _COLLECTION_NAME,
            scroll_filter   = qmodels.Filter(
                must=[qmodels.FieldCondition(
                    key="section_type",
                    match=qmodels.MatchValue(value="header"),
                )]
            ) if True else None,
            limit           = sample_size,
            with_payload    = True,
        )

        if not records:
            return 0.5

        monetary = sum(
            1 for r in records
            if "monetary" in (r.payload.get("company_response") or "").lower()
        )
        return round(monetary / len(records), 3)

    except Exception as e:
        logger.warning(f"Could not compute relief rate: {e}")
        return 0.5
