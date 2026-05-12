"""
Metrics Routes — /metrics
Provides evaluation and calibration data to the dashboard.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from db.session import get_db
from db.models  import Metric, Config

router = APIRouter()


@router.get("/latest")
def get_latest_metrics(db: Session = Depends(get_db)):
    row = db.query(Metric).order_by(Metric.created_at.desc()).first()
    if not row:
        return {}
    return {
        "total_evaluated":       row.total_evaluated,
        "accuracy":              float(row.accuracy)              if row.accuracy else None,
        "precision_score":       float(row.precision_score)       if row.precision_score else None,
        "recall_score":          float(row.recall_score)          if row.recall_score else None,
        "f1_score":              float(row.f1_score)              if row.f1_score else None,
        "dispute_pred_accuracy": float(row.dispute_pred_accuracy) if row.dispute_pred_accuracy else None,
        "created_at":            str(row.created_at),
    }


@router.get("/agent-stats")
def get_agent_stats(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT
            av.agent_name,
            AVG(av.score)    AS mean_score,
            STDDEV(av.score) AS std_score,
            COUNT(*)         AS vote_count,
            CORR(
              av.score,
              CASE WHEN c.company_response ILIKE '%monetary%' THEN 1.0 ELSE 0.0 END
            ) AS correlation_with_outcome
        FROM agent_votes av
        JOIN complaints c ON av.complaint_id = c.complaint_id
        WHERE av.round_num = (
            SELECT MAX(av2.round_num) FROM agent_votes av2 WHERE av2.complaint_id = av.complaint_id
        )
        GROUP BY av.agent_name
    """)).fetchall()
    return {
        r.agent_name: {
            "mean_score":               round(float(r.mean_score or 0), 3),
            "std_score":                round(float(r.std_score or 0), 3),
            "vote_count":               int(r.vote_count),
            "correlation_with_outcome": round(float(r.correlation_with_outcome or 0), 4),
        }
        for r in rows
    }


@router.get("/calibration-history")
def get_calibration_history(db: Session = Depends(get_db)):
    rows = db.query(Config).order_by(Config.created_at.desc()).limit(10).all()
    return {
        "items": [
            {
                "created_at":        str(r.created_at),
                "weight_compliance": float(r.weight_compliance),
                "weight_fairness":   float(r.weight_fairness),
                "weight_financial":  float(r.weight_financial),
                "weight_fraud":      float(r.weight_fraud),
                "weight_reputation": float(r.weight_reputation),
                "notes":             r.notes,
            }
            for r in rows
        ]
    }
