"""
Aggregation Engine — Multi-Agent Financial Complaint Governance Engine

Orchestrates the five governance agents and produces a final weighted decision.

Pipeline:
  1. Run all 5 agents in parallel (Round 1)
  2. Compute weighted score
  3. Apply guardrail overrides (deterministic — independent of LLM)
  4. If score std_dev > DEBATE_THRESHOLD → trigger Round 2 (agents see peer reasoning)
  5. Re-aggregate, produce final decision + confidence + audit trail
"""

import logging
import math
import os
import concurrent.futures
from typing import Any

from agents.compliance_agent  import ComplianceAgent
from agents.fairness_agent    import FairnessAgent
from agents.financial_agent   import FinancialAgent
from agents.fraud_agent       import FraudAgent
from agents.reputation_agent  import ReputationAgent

logger = logging.getLogger(__name__)

DEBATE_THRESHOLD    = float(os.getenv("DEBATE_THRESHOLD",    "2.0"))
COLD_START_PENALTY  = float(os.getenv("COLD_START_PENALTY",  "0.15"))
WEIGHT_COMPLIANCE   = float(os.getenv("WEIGHT_COMPLIANCE",   "0.30"))
WEIGHT_FAIRNESS     = float(os.getenv("WEIGHT_FAIRNESS",     "0.20"))
WEIGHT_FINANCIAL    = float(os.getenv("WEIGHT_FINANCIAL",    "0.20"))
WEIGHT_FRAUD        = float(os.getenv("WEIGHT_FRAUD",        "0.20"))
WEIGHT_REPUTATION   = float(os.getenv("WEIGHT_REPUTATION",   "0.10"))

# Weighted registry — order determines iteration
AGENTS = [
    (ComplianceAgent(),  WEIGHT_COMPLIANCE),
    (FairnessAgent(),    WEIGHT_FAIRNESS),
    (FinancialAgent(),   WEIGHT_FINANCIAL),
    (FraudAgent(),       WEIGHT_FRAUD),
    (ReputationAgent(),  WEIGHT_REPUTATION),
]


# ── Helpers ────────────────────────────────────────────────────────────────

def _weighted_score(votes: list[dict]) -> float:
    """Compute weighted sum of agent scores."""
    weights = {
        "regulatory_compliance": WEIGHT_COMPLIANCE,
        "fairness":              WEIGHT_FAIRNESS,
        "financial_impact":      WEIGHT_FINANCIAL,
        "fraud_pattern":         WEIGHT_FRAUD,
        "reputation_risk":       WEIGHT_REPUTATION,
    }
    total = sum(
        weights.get(v["agent_name"], 0.0) * v["score"]
        for v in votes
    )
    return round(total, 3)


def _std_dev(votes: list[dict]) -> float:
    scores = [v["score"] for v in votes]
    mean   = sum(scores) / len(scores)
    return math.sqrt(sum((s - mean) ** 2 for s in scores) / len(scores))


def _mean_confidence(votes: list[dict]) -> float:
    return round(sum(v["confidence"] for v in votes) / len(votes), 3)


def _variance_penalty(votes: list[dict]) -> float:
    """Reduce confidence when agents disagree significantly."""
    std = _std_dev(votes)
    penalty = min(0.3, std / 10.0)   # max 0.30 penalty
    return round(penalty, 3)


def _score_to_decision(score: float) -> str:
    if score >= 7.0:
        return "Monetary Relief"
    if score >= 4.0:
        return "Explanation Only"
    return "Reject Relief"


# ── Guardrails (deterministic — never overridden by LLM) ───────────────────

def _apply_guardrails(votes: list[dict], decision: str) -> tuple[str, str | None]:
    """
    Returns (final_decision, guardrail_applied_or_None).
    Guardrails override the weighted score entirely.
    """
    all_flags = [f for v in votes for f in v.get("risk_flags", [])]
    compliance_vote = next((v for v in votes if v["agent_name"] == "regulatory_compliance"), None)
    fraud_vote      = next((v for v in votes if v["agent_name"] == "fraud_pattern"), None)

    # Guardrail 1: Regulatory violation detected → force Escalate
    if compliance_vote and "regulatory_violation_detected" in compliance_vote.get("risk_flags", []):
        logger.warning("GUARDRAIL: regulatory_violation_detected → forcing Escalate")
        return "Escalate", "regulatory_violation_detected"

    # Guardrail 2: High fraud score but low evidence → force Reject
    if fraud_vote and fraud_vote["score"] >= 8.0 and "high_score_low_evidence" in fraud_vote.get("risk_flags", []):
        logger.warning("GUARDRAIL: fraud ≥8 + high_score_low_evidence → forcing Reject Relief")
        return "Reject Relief", "fraud_high_score_low_evidence"

    # Guardrail 3: Any ECOA / discriminatory violation → force Escalate
    ecoa_flags = {"ecoa_violation", "discriminatory_treatment", "disparate_impact_confirmed"}
    if ecoa_flags.intersection(set(all_flags)):
        logger.warning(f"GUARDRAIL: ECOA/discrimination flag detected → forcing Escalate")
        return "Escalate", "ecoa_violation_detected"

    return decision, None


# ── Round execution ────────────────────────────────────────────────────────

def _run_round(context: dict, round_num: int, peer_votes: list[dict] | None = None) -> list[dict]:
    """Run all agents concurrently and collect votes."""
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(agent.evaluate, context, round_num, peer_votes): agent.name
            for agent, _ in AGENTS
        }
        for future in concurrent.futures.as_completed(futures):
            agent_name = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                logger.error(f"Agent {agent_name} failed: {e}")
                results.append({
                    "agent_name":   agent_name,
                    "score":        5.0,
                    "confidence":   0.0,
                    "risk_flags":   ["agent_failed"],
                    "reasoning":    f"Agent failed: {str(e)}",
                    "round_num":    round_num,
                    "raw_response": {},
                })
    return results


# ── Main entry point ───────────────────────────────────────────────────────

def run_governance_panel(context: dict[str, Any]) -> dict[str, Any]:
    """
    Full governance panel execution for one complaint.

    Returns:
    {
        "final_score":        float,
        "ai_decision":        str,       # 'Monetary Relief' | 'Explanation Only' | 'Reject Relief' | 'Escalate'
        "ai_confidence":      float,
        "debate_rounds":      int,
        "guardrail_applied":  str | None,
        "agent_votes":        list[dict],
        "all_risk_flags":     list[str],
    }
    """
    cold_start = context.get("cold_start", False)

    # ── Round 1 ───────────────────────────────────────────────────────────
    logger.info("Governance panel: starting Round 1...")
    round1_votes = _run_round(context, round_num=1)
    std = _std_dev(round1_votes)
    debate_rounds = 1
    final_votes = round1_votes

    # ── Round 2 (Debate) — triggered if agents disagree significantly ──────
    if std > DEBATE_THRESHOLD:
        logger.info(f"Score std_dev={std:.2f} > threshold={DEBATE_THRESHOLD} → triggering debate Round 2")
        round2_votes = _run_round(context, round_num=2, peer_votes=round1_votes)
        debate_rounds = 2
        final_votes = round2_votes   # use round 2 results as final

    # ── Aggregation ───────────────────────────────────────────────────────
    raw_score  = _weighted_score(final_votes)
    raw_conf   = _mean_confidence(final_votes)
    raw_std    = _std_dev(final_votes)
    var_pen    = _variance_penalty(final_votes)
    cold_pen   = COLD_START_PENALTY if cold_start else 0.0
    final_conf = max(0.0, round(raw_conf - var_pen - cold_pen, 3))

    decision_label   = _score_to_decision(raw_score)
    final_decision, guardrail = _apply_guardrails(final_votes, decision_label)

    all_flags = sorted(set(f for v in final_votes for f in v.get("risk_flags", [])))
    all_votes = round1_votes + (round2_votes if debate_rounds == 2 else [])

    logger.info(
        f"Panel result: score={raw_score:.2f}, "
        f"decision={final_decision}, confidence={final_conf:.3f}, "
        f"debate_rounds={debate_rounds}, guardrail={guardrail}"
    )

    return {
        "final_score":       raw_score,
        "ai_decision":       final_decision,
        "ai_confidence":     final_conf,
        "debate_rounds":     debate_rounds,
        "guardrail_applied": guardrail,
        "agent_votes":       all_votes,
        "all_risk_flags":    all_flags,
        "score_std_dev":     round(raw_std, 3),
    }
