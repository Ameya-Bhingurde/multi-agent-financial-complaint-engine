"""
Evaluator — Multi-Agent Financial Complaint Governance Engine

Compares AI decisions against actual CFPB company_response outcomes.
Computes accuracy, precision, recall, and dispute prediction accuracy.
Writes results to the `metrics` table.
"""

import logging
from datetime import date

from sqlalchemy import text
from db.session import db_session
from db.models  import Decision, Complaint, Metric

logger = logging.getLogger(__name__)


# ── Decision label mapping ─────────────────────────────────────────────────

def _normalize_cfpb_response(response: str) -> str:
    """
    Map CFPB company_response strings to our three decision labels
    so we can compute agreement_flag.
    """
    r = (response or "").lower()
    if "monetary" in r:
        return "Monetary Relief"
    if "non-monetary" in r or "explanation" in r:
        return "Explanation Only"
    if "closed" in r:
        return "Explanation Only"
    return "Reject Relief"


def _map_decision_to_binary(decision: str) -> int:
    """1 = relief granted, 0 = not granted (for precision/recall)."""
    return 1 if decision in ("Monetary Relief", "Escalate") else 0


# ── Core evaluation ────────────────────────────────────────────────────────

def evaluate_all(limit: int = 0) -> dict:
    """
    Evaluate all decisions that have an actual CFPB outcome available.

    Returns dict with accuracy, precision, recall, and dispute accuracy.
    """
    with db_session() as db:
        # Join decisions with complaints to get actual outcome
        rows = db.execute(text("""
            SELECT
                d.complaint_id,
                d.ai_decision,
                d.ai_confidence,
                d.guardrail_applied,
                c.company_response,
                c.disputed_flag
            FROM decisions d
            JOIN complaints c ON d.complaint_id = c.complaint_id
            WHERE c.company_response IS NOT NULL
              AND c.company_response != ''
            ORDER BY d.created_at DESC
            LIMIT :lim
        """), {"lim": limit if limit else 999999}).fetchall()

    if not rows:
        logger.warning("No decisions with actual outcomes found. Run ingestion + evaluation first.")
        return {}

    total = len(rows)
    correct_decision = 0
    true_pos = false_pos = true_neg = false_neg = 0
    dispute_correct = 0
    dispute_total   = 0

    for row in rows:
        ai_dec     = row.ai_decision
        actual_dec = _normalize_cfpb_response(row.company_response)

        # Agreement
        if ai_dec == actual_dec:
            correct_decision += 1

        # Precision / Recall (binary: relief vs no-relief)
        ai_bin     = _map_decision_to_binary(ai_dec)
        actual_bin = _map_decision_to_binary(actual_dec)

        if ai_bin == 1 and actual_bin == 1:
            true_pos += 1
        elif ai_bin == 1 and actual_bin == 0:
            false_pos += 1
        elif ai_bin == 0 and actual_bin == 1:
            false_neg += 1
        else:
            true_neg += 1

        # Dispute prediction (did consumer dispute? did we escalate/flag?)
        if row.disputed_flag is not None:
            dispute_total += 1
            ai_flagged = 1 if ai_bin == 1 or row.guardrail_applied else 0
            if ai_flagged == int(row.disputed_flag):
                dispute_correct += 1

    accuracy  = round(correct_decision / total, 4)
    precision = round(true_pos / (true_pos + false_pos), 4) if (true_pos + false_pos) else 0.0
    recall    = round(true_pos / (true_pos + false_neg), 4) if (true_pos + false_neg) else 0.0
    f1        = round(2 * precision * recall / (precision + recall), 4) if (precision + recall) else 0.0
    dispute_acc = round(dispute_correct / dispute_total, 4) if dispute_total else 0.0

    metrics = {
        "total_evaluated":        total,
        "accuracy":               accuracy,
        "precision_score":        precision,
        "recall_score":           recall,
        "f1_score":               f1,
        "dispute_pred_accuracy":  dispute_acc,
        "evaluated_on":           str(date.today()),
    }

    logger.info(
        f"Evaluation complete: {total} decisions | "
        f"acc={accuracy:.3f} | prec={precision:.3f} | rec={recall:.3f} | "
        f"f1={f1:.3f} | dispute_acc={dispute_acc:.3f}"
    )

    # Persist to metrics table
    _persist_metrics(metrics)
    return metrics


def _persist_metrics(m: dict):
    """Write a new metrics row."""
    with db_session() as db:
        metric = Metric(
            total_evaluated       = m["total_evaluated"],
            accuracy              = m["accuracy"],
            precision_score       = m["precision_score"],
            recall_score          = m["recall_score"],
            f1_score              = m.get("f1_score"),
            dispute_pred_accuracy = m["dispute_pred_accuracy"],
        )
        db.add(metric)
    logger.info("Metrics persisted to DB.")


def get_latest_metrics() -> dict | None:
    """Fetch the most recent metrics row."""
    with db_session() as db:
        row = db.query(Metric).order_by(Metric.created_at.desc()).first()
        if not row:
            return None
        return {
            "total_evaluated":       row.total_evaluated,
            "accuracy":              float(row.accuracy) if row.accuracy else None,
            "precision_score":       float(row.precision_score) if row.precision_score else None,
            "recall_score":          float(row.recall_score) if row.recall_score else None,
            "f1_score":              float(row.f1_score) if row.f1_score else None,
            "dispute_pred_accuracy": float(row.dispute_pred_accuracy) if row.dispute_pred_accuracy else None,
            "created_at":            str(row.created_at),
        }


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    result = evaluate_all()
    print(result)
