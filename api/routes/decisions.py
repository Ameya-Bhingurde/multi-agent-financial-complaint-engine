"""
Decision Routes — /evaluate

POST /evaluate/{complaint_id}   → run governance panel for a stored complaint
POST /evaluate/inline           → run governance panel for an ad-hoc complaint (no DB needed)

30-second UX contract
─────────────────────
• If the governance panel finishes within 30s → return full resolution immediately AND persist it.
• If it takes longer than 30s → return the complaint_id and status="processing" immediately
  while the panel continues in a background thread and persists the result on its own.
"""

import logging
import httpx
import os
import threading
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.session  import get_db, SessionLocal
from db.models   import Complaint, Decision, AgentVote
from agents.aggregator import run_governance_panel

logger        = logging.getLogger("api.routes.decisions")
router        = APIRouter()
PAGEINDEX_URL = os.getenv("PAGEINDEX_URL", "http://localhost:8001")
RESOLVE_TIMEOUT = 30.0   # seconds — return complaint_id if panel takes longer


# ── Request / Response schemas ────────────────────────────────────────────

class InlineComplaint(BaseModel):
    complaint_id:     Optional[str] = None
    narrative:        str
    product:          str           = "Credit card"
    issue:            str           = "Unknown"
    company_response: Optional[str] = None

class DecisionResponse(BaseModel):
    complaint_id:      str
    status:            str           = "resolved"   # "resolved" | "processing"
    message:           Optional[str] = None
    ai_decision:       Optional[str] = None
    ai_confidence:     Optional[float] = None
    final_score:       Optional[float] = None
    debate_rounds:     Optional[int]   = None
    guardrail_applied: Optional[str]   = None
    all_risk_flags:    Optional[list[str]] = None
    agent_summaries:   Optional[list[dict]] = None


# ── Helpers ────────────────────────────────────────────────────────────────

def _fetch_context(complaint_text: str, product: str, issue: str) -> dict:
    """Call the PageIndex microservice to build agent context."""
    try:
        resp = httpx.post(
            f"{PAGEINDEX_URL}/context",
            json={"complaint_text": complaint_text, "product": product, "issue": issue, "top_k": 5},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"PageIndex unavailable ({e}) — using minimal context.")
        return {
            "complaint_text":         complaint_text,
            "product":                product,
            "issue":                  issue,
            "retrieved_cases":        [],
            "cold_start":             True,
            "policy_excerpt":         "",
            "historical_relief_rate": 0.5,
            "total_similar_found":    0,
        }


def _persist_decision(db: Session, complaint_id: str, panel_result: dict,
                       narrative: str = "", product: str = "", issue: str = ""):
    """Write decision + agent votes to PostgreSQL.
    For inline complaints, auto-creates a parent Complaint row if one doesn't exist.
    """
    # Ensure parent complaint exists (required by FK constraint)
    if not db.get(Complaint, complaint_id):
        db.add(Complaint(
            complaint_id   = complaint_id,
            product        = product or "Credit card",
            issue          = issue   or "Ad-hoc submission",
            narrative      = narrative,
            company        = "Inline submission",
        ))
        db.flush()   # write to DB before inserting Decision

    existing = db.query(Decision).filter_by(complaint_id=complaint_id).first()
    if existing:
        db.delete(existing)
        db.flush()

    decision = Decision(
        complaint_id      = complaint_id,
        final_score       = panel_result["final_score"],
        ai_decision       = panel_result["ai_decision"],
        ai_confidence     = panel_result["ai_confidence"],
        debate_rounds     = panel_result["debate_rounds"],
        guardrail_applied = panel_result.get("guardrail_applied"),
    )
    db.add(decision)

    for vote in panel_result["agent_votes"]:
        db.add(AgentVote(
            complaint_id = complaint_id,
            agent_name   = vote["agent_name"],
            round_num    = vote["round_num"],
            score        = vote["score"],
            confidence   = vote["confidence"],
            risk_flags   = vote.get("risk_flags", []),
            reasoning    = vote.get("reasoning", ""),
            raw_response = vote.get("raw_response", {}),
        ))
    db.commit()


def _background_persist(complaint_id: str, thread: threading.Thread, result_holder: dict):
    """
    Called as a FastAPI background task when the 30s deadline is exceeded.
    Waits for the analysis thread to finish, then persists the result using its own DB session.
    """
    thread.join(timeout=300)   # wait up to 5 more minutes
    if "result" not in result_holder:
        logger.error(f"Background panel for {complaint_id} never completed.")
        return
    db = SessionLocal()
    try:
        _persist_decision(db, complaint_id, result_holder["result"])
        logger.info(f"Background result persisted for {complaint_id}.")
    finally:
        db.close()


def _background_persist_inline(
    complaint_id: str, thread: threading.Thread, result_holder: dict,
    narrative: str = "", product: str = "", issue: str = ""
):
    """Same as _background_persist but passes narrative/product/issue for inline submissions."""
    thread.join(timeout=300)
    if "result" not in result_holder:
        logger.error(f"Background inline panel for {complaint_id} never completed.")
        return
    db = SessionLocal()
    try:
        _persist_decision(db, complaint_id, result_holder["result"],
                          narrative=narrative, product=product, issue=issue)
        logger.info(f"Background inline result persisted for {complaint_id}.")
    finally:
        db.close()


def _build_response(complaint_id: str, panel_result: dict) -> DecisionResponse:
    final_round = panel_result["debate_rounds"]
    return DecisionResponse(
        complaint_id      = complaint_id,
        status            = "resolved",
        ai_decision       = panel_result["ai_decision"],
        ai_confidence     = panel_result["ai_confidence"],
        final_score       = panel_result["final_score"],
        debate_rounds     = panel_result["debate_rounds"],
        guardrail_applied = panel_result.get("guardrail_applied"),
        all_risk_flags    = panel_result["all_risk_flags"],
        agent_summaries   = [
            {
                "agent":      v["agent_name"],
                "score":      v["score"],
                "confidence": v["confidence"],
                "reasoning":  v.get("reasoning", ""),
            }
            for v in panel_result["agent_votes"]
            if v["round_num"] == final_round
        ],
    )


# ── Endpoints ──────────────────────────────────────────────────────────────

# ⚠️  /inline MUST be defined BEFORE /{complaint_id} so FastAPI doesn't
#    match the literal string "inline" as a complaint ID wildcard.

@router.post("/inline", response_model=DecisionResponse)
def evaluate_inline(
    payload: InlineComplaint,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Run the governance panel on an ad-hoc complaint (no pre-stored complaint needed).
    Same 30-second contract as /evaluate/{complaint_id}.
    """
    cid     = payload.complaint_id or f"inline_{uuid.uuid4().hex[:10]}"
    context = _fetch_context(payload.narrative, payload.product, payload.issue)
    result_holder: dict = {}

    def run():
        result_holder["result"] = run_governance_panel(context)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=RESOLVE_TIMEOUT)

    if "result" in result_holder:
        _persist_decision(db, cid, result_holder["result"],
                          narrative=payload.narrative,
                          product=payload.product,
                          issue=payload.issue)
        return _build_response(cid, result_holder["result"])
    else:
        background_tasks.add_task(
            _background_persist_inline,
            cid, thread, result_holder,
            payload.narrative, payload.product, payload.issue
        )
        return DecisionResponse(
            complaint_id = cid,
            status       = "processing",
            message      = (
                f"Analysis is still running. Your complaint ID is '{cid}'. "
                f"The result will be stored automatically once complete."
            ),
        )


@router.post("/{complaint_id}", response_model=DecisionResponse)
def evaluate_stored(
    complaint_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Run the 5-agent governance panel for a complaint already in PostgreSQL.

    30-second contract:
      • Resolves within 30s → returns full decision + agent reasoning
      • Exceeds 30s         → returns complaint_id with status='processing';
                              panel continues in background and is stored automatically.
    """
    complaint: Optional[Complaint] = db.get(Complaint, complaint_id)
    if not complaint:
        raise HTTPException(status_code=404, detail=f"Complaint {complaint_id} not found.")

    context       = _fetch_context(complaint.narrative, complaint.product or "", complaint.issue or "")
    result_holder: dict = {}

    def run():
        result_holder["result"] = run_governance_panel(context)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=RESOLVE_TIMEOUT)

    if "result" in result_holder:
        # ✅ Completed within 30s — persist and return full resolution
        _persist_decision(db, complaint_id, result_holder["result"])
        return _build_response(complaint_id, result_holder["result"])
    else:
        # ⏳ Still processing — hand off to background, return complaint ID immediately
        background_tasks.add_task(_background_persist, complaint_id, thread, result_holder)
        return DecisionResponse(
            complaint_id = complaint_id,
            status       = "processing",
            message      = (
                f"Analysis is taking longer than expected. Your complaint ID is "
                f"'{complaint_id}'. The result will be stored automatically. "
                f"Check again in ~1 minute."
            ),
        )
