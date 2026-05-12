"""
PageIndex Indexer — Multi-Agent Financial Complaint Governance Engine

For each complaint_id:
  1. Fetch complaint from PostgreSQL
  2. Run page_parser → list of page segments
  3. Persist segments to document_pages table
  4. Embed each segment
  5. Upsert vectors into Qdrant with rich metadata payload
  6. Record pointer in embeddings table
"""

import logging
import uuid
from typing import Optional

from db.models import Complaint, DocumentPage, Embedding
from db.session import db_session
from embeddings.embedding_service import embed_batch, get_model_name, get_vector_dim
from embeddings.qdrant_store import create_collection, upsert_vectors, health_check as qdrant_ok
from pageindex.page_parser import parse_complaint

logger = logging.getLogger(__name__)

_COLLECTION_INITIALIZED = False


def _ensure_collection() -> None:
    global _COLLECTION_INITIALIZED
    if not _COLLECTION_INITIALIZED:
        create_collection(vector_dim=get_vector_dim(), recreate=False)
        _COLLECTION_INITIALIZED = True


def index_complaint(complaint_id: str) -> int:
    """
    Index a single complaint. Returns number of page segments indexed.
    """
    _ensure_collection()

    # ── Fetch complaint from DB ────────────────────────────────────────────
    with db_session() as db:
        complaint: Optional[Complaint] = db.get(Complaint, complaint_id)
        if not complaint:
            logger.warning(f"Complaint {complaint_id} not found in DB — skipping.")
            return 0

        # Build page segments
        pages = parse_complaint(
            complaint_id     = complaint.complaint_id,
            narrative        = complaint.narrative,
            product          = complaint.product or "",
            issue            = complaint.issue or "",
            company_response = complaint.company_response or "",
            date_received    = str(complaint.date_received) if complaint.date_received else "",
        )

        if not pages:
            logger.warning(f"No pages generated for complaint {complaint_id}.")
            return 0

        # ── Embed all segments in one batch call ──────────────────────────
        texts = [p["text_content"] for p in pages]
        vectors = embed_batch(texts)

        # ── Build Qdrant point data and DB rows ───────────────────────────
        qdrant_points, db_pages, db_embeddings = [], [], []

        for page_data, vector in zip(pages, vectors):
            page_uuid = uuid.uuid4()

            # DB row for document_pages
            db_pages.append(DocumentPage(
                page_id      = page_uuid,
                complaint_id = complaint_id,
                page_num     = page_data["page_num"],
                section_type = page_data["section_type"],
                text_content = page_data["text_content"],
                token_count  = page_data["token_count"],
                metadata_json= page_data["metadata_json"],
            ))

            # Qdrant point
            qdrant_points.append({
                "id":     page_uuid,
                "vector": vector,
                "payload": {
                    "complaint_id":     complaint_id,
                    "page_num":         page_data["page_num"],
                    "section_type":     page_data["section_type"],
                    "product":          complaint.product or "",
                    "issue":            complaint.issue or "",
                    "company_response": complaint.company_response or "",
                    "resolution":       complaint.company_response or "",
                    "disputed":         complaint.disputed_flag or False,
                    # Short snippet for context preview
                    "text_snippet":     page_data["text_content"][:200],
                },
            })

            # DB row for embeddings pointer
            db_embeddings.append(Embedding(
                page_id         = page_uuid,
                qdrant_point_id = str(page_uuid),
                model_name      = get_model_name(),
                vector_dim      = len(vector),
            ))

        # ── Delete existing pages for this complaint (re-index safe) ──────
        existing = db.query(DocumentPage).filter_by(complaint_id=complaint_id).all()
        for ep in existing:
            db.delete(ep)

        # ── Persist to PostgreSQL ─────────────────────────────────────────
        db.add_all(db_pages)
        db.add_all(db_embeddings)

    # ── Upsert to Qdrant (outside DB transaction) ─────────────────────────
    upsert_vectors(qdrant_points)

    logger.info(f"Indexed complaint {complaint_id}: {len(pages)} page(s).")
    return len(pages)


def index_complaints(complaint_ids: list[str]) -> dict:
    """
    Batch index a list of complaint IDs.
    Returns summary: {total_indexed, total_pages, errors}
    """
    if not qdrant_ok():
        logger.error("Qdrant is unreachable — cannot index.")
        return {"total_indexed": 0, "total_pages": 0, "errors": len(complaint_ids)}

    _ensure_collection()
    total_pages = 0
    errors = 0

    for i, cid in enumerate(complaint_ids):
        try:
            pages = index_complaint(cid)
            total_pages += pages
        except Exception as e:
            logger.error(f"Failed to index complaint {cid}: {e}")
            errors += 1

        if (i + 1) % 50 == 0:
            logger.info(f"Indexed {i + 1}/{len(complaint_ids)} complaints...")

    logger.info(
        f"Batch indexing complete: "
        f"{len(complaint_ids) - errors} indexed, "
        f"{total_pages} total pages, "
        f"{errors} errors."
    )
    return {
        "total_indexed": len(complaint_ids) - errors,
        "total_pages":   total_pages,
        "errors":        errors,
    }
