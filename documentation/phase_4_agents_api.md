# Phase 4 — Multi-Agent Engine + FastAPI

**Status:** ✅ Complete  
**Goal:** Implement the five-agent governance panel with weighted scoring, debate mechanism, deterministic guardrails, and expose it as a production FastAPI service.

---

## Overview

Phase 4 is the core intelligence of the system — where individual LLM agents deliberate over a complaint and produce an audit-ready decision. The design philosophy is:

> *"Every decision must be explainable, reproducible, and auditable. LLM opinions are inputs; deterministic guardrails are final."*

---

## Files Created

```
agents/
├── __init__.py
├── base_agent.py
├── compliance_agent.py
├── fairness_agent.py
├── financial_agent.py
├── fraud_agent.py
├── reputation_agent.py
└── aggregator.py

api/
├── __init__.py
├── Dockerfile
├── main.py
└── routes/
    ├── __init__.py
    ├── decisions.py
    └── complaints.py
```

---

## 1. `agents/base_agent.py`

### What it does
Abstract base class all five agents inherit from. Handles all shared infrastructure so individual agents only define their `system_prompt` and `focus_description`.

### LLM Routing

```python
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")  # "groq" or "openai"
```

Both providers enforce **JSON output mode** at the API level:
- Groq: `response_format={"type": "json_object"}` on `llama-3.3-70b-versatile`
- OpenAI: `response_format={"type": "json_object"}` on `gpt-4o`

This means the LLM is structurally constrained to return valid JSON — no regex parsing.

### Retry Logic

Up to **1 retry** with a 2s wait before re-raising. If the call fails after the retry, the aggregator records it as an `agent_failed` vote with a neutral score of 5.0 rather than crashing the whole panel.

### Two-Round Prompt Structure

**Round 1:** Agent sees complaint + similar cases + policy excerpt → scores independently.

**Round 2 (debate):** If disagreement among agents is high (`std_dev > threshold`), each agent additionally sees all peer agents' Round 1 scores and reasoning before re-scoring. This simulates an expert panel deliberation.

### Output Schema (enforced)
```json
{
  "score":      7.5,
  "confidence": 0.82,
  "risk_flags": ["billing_dispute_unresolved", "regulatory_z_violation"],
  "reasoning":  "The company failed to resolve the billing dispute within the 90-day window required by Regulation Z § 1026.13..."
}
```

---

## 2. Five Governance Agents

| Agent | File | Weight | Focus |
|---|---|---|---|
| Regulatory Compliance | `compliance_agent.py` | **30%** | FCRA, ECOA, CARD Act, Regulation Z, FCBA violations |
| Fairness | `fairness_agent.py` | **20%** | Disparate impact, protected class signals, ECOA equity |
| Financial Impact | `financial_agent.py` | **20%** | Monetary harm, billing errors, withheld funds |
| Fraud Pattern | `fraud_agent.py` | **20%** | Unauthorized transactions, identity theft, evidence quality |
| Reputation Risk | `reputation_agent.py` | **10%** | Media escalation, class-action risk, CFPB visibility |

Each agent extends `BaseAgent` with only two properties: `system_prompt` (deep domain expertise) and `focus_description` (evaluation lens).

**Weight rationale:**
- Compliance leads at 30% because regulatory violations have hard legal consequences
- Fairness, financial, and fraud share equal weight as the core substantive harms
- Reputation is lowest weight as it's a secondary business concern, not a consumer rights issue

---

## 3. `agents/aggregator.py`

### What it does
Orchestrates the full 5-agent panel and produces the final weighted decision.

### Full Execution Flow

```
                        context (from PageIndex)
                               │
                ┌──────────────┼──────────────┐
                │              │              │
           [Compliance]  [Fairness]   [Financial]  [Fraud]  [Reputation]
                │   concurrent.futures.ThreadPoolExecutor(max_workers=5)
                └──────────────┼──────────────┘
                               │
                       Round 1 votes (5 scores)
                               │
                    std_dev > DEBATE_THRESHOLD?
                      │                    │
                     YES                   NO
                      │                    │
              Round 2 with peer          Use Round 1
              reasoning shared           votes as final
                      │
                  Final votes
                      │
              weighted_score = Σ(weight_i × score_i)
                      │
              decision = score_to_label(score)
                      │
              apply_guardrails(votes, decision)
                      │
              final confidence = mean(confidences)
                                 − variance_penalty
                                 − cold_start_penalty
```

### Weighted Score Formula

```
final_score =
  0.30 × compliance_score +
  0.20 × fairness_score   +
  0.20 × financial_score  +
  0.20 × fraud_score      +
  0.10 × reputation_score
```

### Decision Labels

| Score Range | Decision |
|---|---|
| ≥ 7.0 | **Monetary Relief** |
| 4.0 – 6.9 | **Explanation Only** |
| < 4.0 | **Reject Relief** |
| (guardrail) | **Escalate** |

### Confidence Formula

```
confidence = mean(agent_confidences)
             − variance_penalty      (max 0.30, based on score std_dev)
             − cold_start_penalty    (0.15, if < 5 similar cases found)
```

Confidence reflects **how certain the panel is**, not just how severe the complaint is.

### Three Deterministic Guardrails

These run **after** the weighted score and **override it completely** regardless of LLM output:

| Guardrail | Trigger Condition | Forced Decision |
|---|---|---|
| `regulatory_violation_detected` | Compliance agent flags this in `risk_flags` | **Escalate** |
| `fraud_high_score_low_evidence` | Fraud score ≥ 8.0 AND `high_score_low_evidence` flag | **Reject Relief** |
| `ecoa_violation_detected` | Any agent flags `ecoa_violation`, `discriminatory_treatment`, or `disparate_impact_confirmed` | **Escalate** |

> Guardrails are deterministic Python code — they cannot be overridden by any LLM response.

### Debate Mechanism

Standard deviation of agent scores is computed after Round 1:
- If `std_dev ≤ 2.0` → panel agreement is sufficient, use Round 1 results
- If `std_dev > 2.0` → significant disagreement, trigger Round 2

In Round 2 each agent sees all peer scores and reasoning. This mimics real expert panel deliberation where minority views can influence the majority.

---

## 4. `api/main.py`

FastAPI application with:
- CORS middleware (all origins — tighten for production)
- `/health` endpoint checking PostgreSQL + Qdrant connectivity
- Route registration: `/evaluate` and `/complaints`
- Interactive docs at `/docs` and `/redoc`

---

## 5. `api/routes/decisions.py`

### 30-Second UX Contract

The `/evaluate` endpoint implements a **30-second response promise**:

```
Consumer submits complaint
        ↓
   Panel starts (5 agents parallel, PageIndex context)
        ↓
   ┌────── within 30s ──────┐
   │                        │
✅ returns full resolution   ⏳ returns complaint_id
   AND stores to DB          status="processing"
                             (panel keeps running in background,
                              auto-stores result when finished)
```

The user is always **unblocked within 30 seconds**. If they get a complaint ID, they can paste it into the Status Search page or call `GET /complaints/{id}` to retrieve the full resolution once it's ready.

### `POST /evaluate/{complaint_id}`
Full governance panel for a complaint stored in PostgreSQL.

**Fast path (< 30s):** Returns full `DecisionResponse` with all agent scores, decision label, confidence, and reasoning. Result is persisted to PostgreSQL synchronously.

**Slow path (> 30s):** Returns immediately with:
```json
{
  "complaint_id": "19356376",
  "status": "processing",
  "message": "Analysis in progress. Your complaint ID is '19356376'. Check status later."
}
```
The background thread continues and writes to DB when complete.

### `POST /evaluate/inline`
Ad-hoc evaluation without requiring a stored complaint. Same 30-second contract. Accepts raw narrative + product + issue.

### PageIndex Graceful Fallback
If the PageIndex service is unavailable, the endpoint falls back to a **minimal context** (`cold_start=True`) rather than crashing. The panel still runs with reduced confidence due to the cold-start penalty.

---

## 6. `api/routes/complaints.py`

Read-only complaint endpoints:
- `GET /complaints/` — paginated list with optional `product` filter
- `GET /complaints/{id}` — full complaint detail with embedded decision (if exists)

---

## Sample API Calls

```bash
# Evaluate a stored complaint
curl -X POST http://localhost:8000/evaluate/19356376

# Evaluate an inline complaint
curl -X POST http://localhost:8000/evaluate/inline \
  -H "Content-Type: application/json" \
  -d '{
    "narrative": "My bank charged me $540 without authorization and when I disputed it they never responded even after 60 days.",
    "product": "Credit card",
    "issue": "Problem with a purchase shown on your statement"
  }'

# Sample response
{
  "complaint_id":      "inline_...",
  "ai_decision":       "Monetary Relief",
  "ai_confidence":     0.78,
  "final_score":       7.4,
  "debate_rounds":     1,
  "guardrail_applied": null,
  "all_risk_flags":    ["billing_dispute_unresolved", "regulation_z_breach"],
  "agent_summaries": [
    {"agent": "regulatory_compliance", "score": 8.2, "confidence": 0.85,
     "reasoning": "Company violated Regulation Z § 1026.13 by failing to respond within 90 days..."},
    {"agent": "fairness",              "score": 5.1, "confidence": 0.70, "reasoning": "..."},
    {"agent": "financial_impact",      "score": 7.8, "confidence": 0.80, "reasoning": "..."},
    {"agent": "fraud_pattern",         "score": 6.9, "confidence": 0.65, "reasoning": "..."},
    {"agent": "reputation_risk",       "score": 6.2, "confidence": 0.72, "reasoning": "..."}
  ]
}
```

---

## How to Verify Phase 4

```bash
# 1. Start all services
docker compose up -d

# 2. Run ingestion + indexing
python ingestion/run_ingestion.py --limit 20

# 3. Check FastAPI is healthy
curl http://localhost:8000/health
# Expected: {"status": "ok", "postgres": true, "qdrant": true, "llm_provider": "groq"}

# 4. List available complaints
curl http://localhost:8000/complaints/?limit=5

# 5. Evaluate one complaint (use an ID from step 4)
curl -X POST http://localhost:8000/evaluate/<complaint_id>

# 6. Verify decision was persisted
docker exec cfpb_postgres psql -U cfpb -d complaints_db \
  -c "SELECT complaint_id, ai_decision, ai_confidence, debate_rounds FROM decisions LIMIT 5;"

# 7. Verify agent votes were recorded
docker exec cfpb_postgres psql -U cfpb -d complaints_db \
  -c "SELECT agent_name, score, confidence FROM agent_votes WHERE complaint_id='<id>' ORDER BY agent_name;"

# 8. Test inline evaluation (no DB complaint required)
curl -X POST http://localhost:8000/evaluate/inline \
  -H "Content-Type: application/json" \
  -d '{"narrative": "Unauthorized charge of $800 on my credit card, dispute ignored for 90 days.", "product": "Credit card", "issue": "Billing dispute"}'
```
