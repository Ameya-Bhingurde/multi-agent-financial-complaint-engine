"""
PageIndex FastAPI Microservice — Multi-Agent Financial Complaint Governance Engine

Exposes the segmentation and retrieval logic as a REST API
so the main FastAPI app and n8n can call it over HTTP.

Endpoints:
  POST /parse          → parse a complaint into page segments
  POST /index/{id}     → index a single complaint (fetch from PG + embed + Qdrant)
  POST /index/batch    → batch index a list of complaint IDs
  POST /retrieve       → retrieve similar cases for a complaint text
  POST /context        → build full context JSON for agents
  GET  /health         → health check
  GET  /stats          → collection stats
"""

import logging
import os
import sys

sys.path.insert(0, "/app")

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from pageindex.page_parser    import parse_complaint
from pageindex.indexer        import index_complaint, index_complaints
from pageindex.retriever      import retrieve_similar_cases, get_historical_relief_rate
from pageindex.context_builder import build_context
from embeddings.qdrant_store  import get_collection_info, health_check as qdrant_ok, create_collection
from embeddings.embedding_service import get_vector_dim

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pageindex.service")

app = FastAPI(
    title       = "PageIndex Microservice",
    description = "Hierarchical document segmentation and RAG retrieval for CFPB complaints",
    version     = "1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    try:
        create_collection(vector_dim=get_vector_dim(), recreate=False)
        logger.info("Qdrant collection ready.")
    except Exception as e:
        logger.warning(f"Could not initialise Qdrant collection on startup: {e}")


# ── Request/Response models ────────────────────────────────────────────────

class ParseRequest(BaseModel):
    complaint_id:     str
    narrative:        str
    product:          str
    issue:            str
    company_response: Optional[str] = ""
    date_received:    Optional[str] = ""

class IndexBatchRequest(BaseModel):
    complaint_ids: list[str]

class RetrieveRequest(BaseModel):
    complaint_text: str
    product:        Optional[str] = None
    issue:          Optional[str] = None
    top_k:          int = 5

class ContextRequest(BaseModel):
    complaint_text: str
    product:        str
    issue:          str
    top_k:          int = 5
    extra_metadata: Optional[dict] = None


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "qdrant": qdrant_ok(),
    }


@app.get("/stats")
def stats():
    try:
        return get_collection_info()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/parse")
def parse(req: ParseRequest):
    """Parse a complaint into hierarchical page segments (no DB/Qdrant write)."""
    pages = parse_complaint(
        complaint_id     = req.complaint_id,
        narrative        = req.narrative,
        product          = req.product,
        issue            = req.issue,
        company_response = req.company_response,
        date_received    = req.date_received,
    )
    return {"complaint_id": req.complaint_id, "pages": pages}


@app.post("/index/{complaint_id}")
def index_one(complaint_id: str):
    """Fetch complaint from DB, segment, embed, and store in Qdrant."""
    try:
        count = index_complaint(complaint_id)
        return {"complaint_id": complaint_id, "pages_indexed": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/index/batch")
def index_batch(req: IndexBatchRequest):
    """Batch index multiple complaints."""
    result = index_complaints(req.complaint_ids)
    return result


@app.post("/retrieve")
def retrieve(req: RetrieveRequest):
    """Retrieve similar past complaint cases from Qdrant."""
    result = retrieve_similar_cases(
        complaint_text = req.complaint_text,
        product        = req.product,
        issue          = req.issue,
        top_k          = req.top_k,
    )
    return result


@app.post("/context")
def context(req: ContextRequest):
    """Build the full structured context JSON for LLM agents."""
    retrieval_result = retrieve_similar_cases(
        complaint_text = req.complaint_text,
        product        = req.product,
        issue          = req.issue,
        top_k          = req.top_k,
    )
    relief_rate = get_historical_relief_rate(product=req.product)
    ctx = build_context(
        complaint_text          = req.complaint_text,
        product                 = req.product,
        issue                   = req.issue,
        retrieval_result        = retrieval_result,
        historical_relief_rate  = relief_rate,
        extra_metadata          = req.extra_metadata,
    )
    return ctx
