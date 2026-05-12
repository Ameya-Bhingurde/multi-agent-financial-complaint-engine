"""
FastAPI Main Application — Multi-Agent Financial Complaint Governance Engine

Exposes the governance engine as a REST API.

Endpoints:
  POST /evaluate          → run full 5-agent panel for a complaint
  GET  /decision/{id}     → fetch stored decision for a complaint
  GET  /complaints        → list complaints with optional filters
  GET  /health            → service health check
"""

import logging
import os
import sys

sys.path.insert(0, "/app")

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from db.session  import get_db
from db.models   import Complaint, Decision, AgentVote
from api.routes  import decisions, complaints, metrics

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api.main")

app = FastAPI(
    title       = "Multi-Agent Financial Complaint Governance Engine",
    description = (
        "Evaluates CFPB consumer complaints using a 5-agent governance panel "
        "backed by Groq (Llama 3) or OpenAI (GPT-4o), with PageIndex RAG retrieval "
        "and deterministic guardrails."
    ),
    version     = "1.0.0",
    docs_url    = "/docs",
    redoc_url   = "/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins  = ["*"],
    allow_methods  = ["*"],
    allow_headers  = ["*"],
)

# ── Route registration ─────────────────────────────────────────────────────
app.include_router(decisions.router,   prefix="/evaluate",   tags=["Governance"])
app.include_router(complaints.router,  prefix="/complaints",  tags=["Complaints"])


@app.get("/health", tags=["System"])
def health(db: Session = Depends(get_db)):
    from embeddings.qdrant_store import health_check as qdrant_ok
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        pg_ok = True
    except Exception:
        pg_ok = False

    return {
        "status":    "ok" if (pg_ok) else "degraded",
        "postgres":  pg_ok,
        "qdrant":    qdrant_ok(),
        "llm_provider": os.getenv("LLM_PROVIDER", "groq"),
    }


@app.get("/", tags=["System"])
def root():
    return {
        "service":  "Multi-Agent Financial Complaint Governance Engine",
        "version":  "1.0.0",
        "docs":     "/docs",
    }
