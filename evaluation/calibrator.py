"""
Calibrator — Multi-Agent Financial Complaint Governance Engine

Analyses evaluation metrics + agent vote distributions to detect drift
and suggest updated agent weights. Writes calibration recommendations
to the `config` table (versioned — never overwrites, always inserts).
"""

import logging
import os
from datetime import date

from sqlalchemy import text
from db.session import db_session
from db.models  import Config

logger = logging.getLogger(__name__)

DRIFT_THRESHOLD = 0.05   # if accuracy drops > 5% from baseline, recommend recalibration


def _get_agent_score_stats() -> dict:
    """
    Compute per-agent mean score and correlation with actual outcome
    (Monetary Relief = 1, else = 0) from the agent_votes table.
    """
    with db_session() as db:
        rows = db.execute(text("""
            SELECT
                av.agent_name,
                AVG(av.score)       AS mean_score,
                STDDEV(av.score)    AS std_score,
                COUNT(*)            AS vote_count,
                AVG(
                  CASE WHEN c.company_response ILIKE '%monetary%' THEN 1.0 ELSE 0.0 END
                ) AS actual_relief_rate,
                CORR(
                  av.score,
                  CASE WHEN c.company_response ILIKE '%monetary%' THEN 1.0 ELSE 0.0 END
                ) AS correlation_with_outcome
            FROM agent_votes av
            JOIN complaints c ON av.complaint_id = c.complaint_id
            WHERE av.round_num = (
                SELECT MAX(round_num) FROM agent_votes av2
                WHERE av2.complaint_id = av.complaint_id
            )
            GROUP BY av.agent_name
        """)).fetchall()

    return {
        row.agent_name: {
            "mean_score":             float(row.mean_score or 0),
            "std_score":              float(row.std_score or 0),
            "vote_count":             int(row.vote_count),
            "actual_relief_rate":     float(row.actual_relief_rate or 0),
            "correlation_with_outcome": float(row.correlation_with_outcome or 0),
        }
        for row in rows
    }


def _suggest_weights(agent_stats: dict) -> dict:
    """
    Suggest new weights proportional to each agent's correlation with
    actual CFPB outcomes, with a minimum weight floor of 0.05.

    Returns dict of {agent_name: suggested_weight}.
    """
    agents = [
        "regulatory_compliance",
        "fairness",
        "financial_impact",
        "fraud_pattern",
        "reputation_risk",
    ]

    correlations = {
        a: max(0.0, agent_stats.get(a, {}).get("correlation_with_outcome", 0.0))
        for a in agents
    }

    total_corr = sum(correlations.values()) or 1.0
    MIN_WEIGHT = 0.05

    raw_weights = {a: correlations[a] / total_corr for a in agents}

    # Apply floor and renormalize
    floored = {a: max(MIN_WEIGHT, w) for a, w in raw_weights.items()}
    total_floored = sum(floored.values())
    normalized = {a: round(w / total_floored, 4) for a, w in floored.items()}

    return normalized


def run_calibration() -> dict:
    """
    Main calibration entry point.
    Returns calibration report dict.
    """
    logger.info("Starting calibration run...")
    agent_stats    = _get_agent_score_stats()

    if not agent_stats:
        logger.warning("No agent vote data found. Skipping calibration.")
        return {"status": "skipped", "reason": "no_data"}

    suggested = _suggest_weights(agent_stats)

    # Load current weights from env
    current = {
        "regulatory_compliance": float(os.getenv("WEIGHT_COMPLIANCE",  "0.30")),
        "fairness":              float(os.getenv("WEIGHT_FAIRNESS",    "0.20")),
        "financial_impact":      float(os.getenv("WEIGHT_FINANCIAL",   "0.20")),
        "fraud_pattern":         float(os.getenv("WEIGHT_FRAUD",       "0.20")),
        "reputation_risk":       float(os.getenv("WEIGHT_REPUTATION",  "0.10")),
    }

    changes = {
        a: round(suggested[a] - current.get(a, 0), 4)
        for a in suggested
    }
    significant_change = any(abs(d) >= 0.03 for d in changes.values())

    report = {
        "date":              str(date.today()),
        "current_weights":   current,
        "suggested_weights": suggested,
        "weight_deltas":     changes,
        "significant_change": significant_change,
        "agent_stats":       agent_stats,
        "recommendation":    (
            "Apply suggested weights to .env and restart API."
            if significant_change else
            "Weights are stable — no recalibration needed."
        ),
    }

    # Always persist suggested weights to config table (versioned)
    _persist_config(suggested, report)

    logger.info(f"Calibration complete. Significant change: {significant_change}")
    for a, delta in changes.items():
        logger.info(f"  {a}: {current.get(a, '?')} → {suggested[a]} (Δ {delta:+.4f})")

    return report


def _persist_config(weights: dict, report: dict):
    """Insert a new config row with suggested weights (never updates existing rows)."""
    with db_session() as db:
        config = Config(
            weight_compliance  = weights["regulatory_compliance"],
            weight_fairness    = weights["fairness"],
            weight_financial   = weights["financial_impact"],
            weight_fraud       = weights["fraud_pattern"],
            weight_reputation  = weights["reputation_risk"],
            debate_threshold   = float(os.getenv("DEBATE_THRESHOLD", "2.0")),
            cold_start_penalty = float(os.getenv("COLD_START_PENALTY", "0.15")),
            notes              = f"Auto-calibration {report['date']} | "
                                 f"significant_change={report['significant_change']}",
        )
        db.add(config)
    logger.info("Calibration config persisted to DB.")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    result = run_calibration()
    import json
    print(json.dumps(result, indent=2))
