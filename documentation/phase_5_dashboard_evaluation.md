# Phase 5 — Dashboard + Evaluation + n8n Workflows + Policy Layer

**Status:** ✅ Complete  
**Goal:** Build the consumer-facing Streamlit dashboard (3 pages), implement the 30-second complaint resolution UX, index real credit card T&C policy documents, add bulk evaluation tooling, and automate the weekly pipeline with n8n.

---

## Overview

```
[Consumer submits complaint via "New Complaint" Sidebar]
        ↓
[POST /evaluate/inline — 5-agent panel with 30s timeout]
        ↓
   ┌──────────────────────┐
   │ <30s → full result   │
   │ >30s → complaint ID  │  (background thread stores result)
   └──────────────────────┘
        ↓
[Dashboard renders Decision Summary Card with dynamic crux]
        ↓
[Chatbot conversation begins — Liable Company Persona answers questions]
        ↓
[Evaluator → Metrics → Calibrator (weekly via n8n)]
```

---

## Files

```
dashboard/app.py              ← 2-page Streamlit dashboard (Home & Chatbot)
evaluation/evaluator.py       ← AI vs CFPB outcome metrics
evaluation/calibrator.py      ← agent weight drift detection
api/routes/metrics.py         ← /metrics endpoints for dashboard
scripts/bulk_evaluate.py      ← batch evaluation of all pending complaints
policies/                     ← real credit card T&C policy documents
  cfpb_regulatory_framework.txt
  chase_credit_card_agreement.txt
  capital_one_credit_card_agreement.txt
  citibank_credit_card_agreement.txt
  index_policies.py           ← indexes policy docs into Qdrant
n8n/weekly_governance_pipeline.json
```

---

## 1. `evaluation/evaluator.py`

### What it does
Compares every AI decision in the `decisions` table against the actual CFPB `company_response` field in the `complaints` table. Computes five metrics and persists a new row to the `metrics` table.

### CFPB Response → Decision Label Mapping

| CFPB company_response | Maps to |
|---|---|
| `"Closed with monetary relief"` | **Monetary Relief** |
| `"Closed with non-monetary relief"` / `"Closed with explanation"` | **Explanation Only** |
| `"Closed without relief"` / `"Untimely response"` | **Reject Relief** |

### Metrics Computed

| Metric | Definition |
|---|---|
| **Accuracy** | % of cases where AI decision label matches CFPB actual label |
| **Precision** | Of AI relief grants, what % were correct (CFPB also granted relief) |
| **Recall** | Of actual relief grants by CFPB, what % did AI correctly predict |
| **F1 Score** | Harmonic mean of precision and recall |
| **Dispute Accuracy** | % of consumer disputes correctly flagged by AI escalation behaviour |

### Running Evaluation
```bash
python evaluation/evaluator.py
# or via Makefile:
make eval
```

---

## 2. `evaluation/calibrator.py`

### What it does
Queries the `agent_votes` table and computes each agent's **correlation with actual CFPB outcomes**. Uses this to suggest updated weights proportional to each agent's predictive power. Persists suggestions as a new versioned `Config` row (never overwrites history).

### Algorithm

```
1. For each agent, compute CORR(agent_score, actual_relief_binary)
   using PostgreSQL CORR() aggregate
   
2. Normalize correlations to sum to 1.0 (with floor of 0.05 per agent)

3. Compare to current weights from environment variables

4. If any weight delta >= 0.03 → mark as significant_change = True

5. Persist new Config row with suggested weights + timestamp
```

### How to Apply New Weights
```bash
# 1. Run calibration
python evaluation/calibrator.py

# 2. Read suggested weights from DB or Calibration page in dashboard
docker exec cfpb_postgres psql -U cfpb -d complaints_db \
  -c "SELECT * FROM config ORDER BY created_at DESC LIMIT 1;"

# 3. Update .env with new weights
# 4. Restart API container
docker compose restart fastapi-app
```

---

## 3. `dashboard/app.py` — Streamlit Consumer Chatbot

The dashboard has been completely refactored into a single-page **Consumer Complaint Assistant UI** featuring a dark theme and sidebar navigation.

#### 🗂️ Sidebar Navigation
1. **New Complaint**: A form where users input their narrative, product, and issue. Upon submission, it queries the backend 5-Agent Governance Panel, generating a Complaint ID and rendering a detailed Decision Summary Card.
2. **Policies & Rules**: Switches the chatbot context to act as an educational assistant answering questions about financial regulations (Reg Z, FCBA, ECOA, CARD Act).
3. **Track My Complaint**: Allows users to input an existing `CPL-XXXXX` ID to resume their session and understand the prior decision.

#### 💬 Main Chat Panel
- Groq-powered AI assistant acting as a liable company representative, providing empathetic, detailed plain-English explanations of the AI panel's findings.
- Dynamically generates one-sentence summary 'cruxes' for the UI card while reserving lengthy legal breakdowns for the chat stream.
- Strict guarding against hallucinating refunds or directing consumers to third-party regulators contrary to company interests.

### Running the Dashboard
```bash
streamlit run dashboard/app.py --server.port 8501
# → Open http://localhost:8501
```

---

## 4. `api/routes/metrics.py`

Three endpoints serving the dashboard:

| Endpoint | Description |
|---|---|
| `GET /stats` | Real-time database aggregations (totals, distributions, averages) |
| `GET /metrics/latest` | Most recent evaluation metrics row |
| `GET /metrics/agent-stats` | Per-agent correlation + score stats |
| `GET /metrics/calibration-history` | Last 10 calibration config rows |

---

## 5. `n8n/weekly_governance_pipeline.json`

### Workflow: Weekly Governance Pipeline

Imports directly into n8n via **Import from file** → `n8n/weekly_governance_pipeline.json`.

**Node sequence:**

```
Weekly Trigger (Monday 2 AM)
        ↓
Health Check → [fastapi-app:8000/health]
        ↓
IF status == 'ok'
    ├── [TRUE]
    │     ├── Fetch Pending Complaints → Split Into Items → Run Governance Panel
    │     └── Run Evaluation → Run Calibration → Fetch Final Metrics
    │                                                     ↓
    │                               IF accuracy < 60%
    │                                   └── Build Alert Message → Send Email Alert
    └── [FALSE] → (workflow ends silently)
```

**What each step does:**

| Node | Action |
|---|---|
| Weekly Trigger | Fires every Monday at 02:00 |
| Health Check | Confirms API and Qdrant are live before doing work |
| Fetch Pending Complaints | Calls `GET /complaints/?filter=pending&limit=50` |
| Run Governance Panel | `POST /evaluate/{complaint_id}` for each (parallelized via split) |
| Run Evaluation | Computes accuracy vs CFPB outcomes |
| Run Calibration | Analyses agent weight drift |
| Accuracy Below 60%? | Conditional: if accuracy dropped below 60% |
| Send Email Alert | Sends alert to compliance team with current metrics |

### How to Import into n8n
```bash
# 1. Open n8n at http://localhost:5678
# 2. Click + New Workflow → ... → Import from File
# 3. Select: n8n/weekly_governance_pipeline.json
# 4. Configure SMTP credentials for the email node
# 5. Activate the workflow
```

---

## Complete System Verification

```bash
# 1. Start all services
docker compose up -d

# 2. Ingest + index complaints
python ingestion/run_ingestion.py --limit 50

# 3. Evaluate a few complaints
curl -X POST http://localhost:8000/evaluate/19356376
curl -X POST http://localhost:8000/evaluate/inline \
  -H "Content-Type: application/json" \
  -d '{"narrative": "Unauthorized charge of $800, dispute ignored 90 days.", "product": "Credit card", "issue": "Billing dispute"}'

# 4. Run evaluation
python evaluation/evaluator.py

# 5. Run calibration
python evaluation/calibrator.py

# 6. Launch dashboard
streamlit run dashboard/app.py
# → Open http://localhost:8501

# 7. Import n8n workflow → activate weekly pipeline

# 8. Check metrics endpoint
curl http://localhost:8000/metrics/latest
```

Expected: dashboard loads with KPI cards populated, agent charts visible, decisions render with colour-coded badges.
