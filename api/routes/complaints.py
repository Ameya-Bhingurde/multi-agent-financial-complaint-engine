"""
Complaint Routes — /complaints

GET /complaints/stats      → real-time system stats (no pagination limit)
GET /complaints            → paginated list of complaints
GET /complaints/{id}       → single complaint with its decision
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from db.session import get_db
from db.models  import Complaint, Decision

router = APIRouter()


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    """Real-time counts and decision distribution from DB."""
    total     = db.query(func.count(Complaint.complaint_id)).scalar() or 0
    decided   = db.query(func.count(Decision.complaint_id)).scalar() or 0
    dist_rows = (
        db.query(Decision.ai_decision, func.count(Decision.complaint_id))
        .group_by(Decision.ai_decision).all()
    )
    avg_conf  = db.query(func.avg(Decision.ai_confidence)).scalar()
    avg_score = db.query(func.avg(Decision.final_score)).scalar()
    return {
        "total_complaints": total,
        "total_decisions":  decided,
        "pending":          total - decided,
        "decision_distribution": {label: cnt for label, cnt in dist_rows},
        "avg_confidence":   round(float(avg_conf  or 0), 3),
        "avg_score":        round(float(avg_score or 0), 3),
    }



@router.get("/")
def list_complaints(
    skip:    int = Query(0,  ge=0),
    limit:   int = Query(20, ge=1, le=200),
    product: str = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Complaint)
    if product:
        q = q.filter(Complaint.product.ilike(f"%{product}%"))
    total = q.count()
    items = q.offset(skip).limit(limit).all()
    return {
        "total": total,
        "skip":  skip,
        "items": [
            {
                "complaint_id": c.complaint_id,
                "product":      c.product,
                "issue":        c.issue,
                "company":      c.company,
                "date_received": str(c.date_received) if c.date_received else None,
                "has_decision": bool(c.decision),
            }
            for c in items
        ],
    }


@router.get("/{complaint_id}")
def get_complaint(complaint_id: str, db: Session = Depends(get_db)):
    c: Complaint = db.get(Complaint, complaint_id)
    if not c:
        raise HTTPException(status_code=404, detail="Complaint not found.")
    d: Decision = db.query(Decision).filter_by(complaint_id=complaint_id).first()
    return {
        "complaint_id":   c.complaint_id,
        "product":        c.product,
        "issue":          c.issue,
        "company":        c.company,
        "narrative":      c.narrative,
        "company_response": c.company_response,
        "disputed_flag":  c.disputed_flag,
        "date_received":  str(c.date_received) if c.date_received else None,
        "decision": {
            "ai_decision":       d.ai_decision,
            "ai_confidence":     d.ai_confidence,
            "final_score":       d.final_score,
            "debate_rounds":     d.debate_rounds,
            "guardrail_applied": d.guardrail_applied,
        } if d else None,
    }
