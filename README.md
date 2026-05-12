---
title: Multi-Agent Financial Complaint Governance Engine
emoji: ⚖️
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
---

# Multi-Agent Financial Complaint Governance Engine

> A production-grade agentic system that evaluates consumer complaints using real CFPB resolution data, enforces policy constraints, and produces audit-ready decision recommendations.

---

## Architecture

```
[CFPB REST API / CSV]
        ↓
[n8n Ingestion Workflow]
        ↓
[PostgreSQL — Structured Complaints]
        ↓
[PageIndex Service — Hierarchical Segmentation]
        ↓
[Embedding Service — BGE-small (Local)]
        ↓
[Qdrant — Metadata-Tagged Vector Store]

─────────────────────────────────────────────────────────────

[Streamlit Dashboard / API Client]
        ↓
[FastAPI — Port 8000]
        ↓
[PageIndex Retriever — Metadata-Filtered Top-K]
        ↓
[Context Builder — Token-Limited Structured JSON]
        ↓
[5 Parallel LLM Agents — Groq Llama 3]
        ↓
[Debate & Aggregation Engine]
        ↓
[Decision + Audit Log → PostgreSQL]
        ↓
[Evaluator — vs CFPB Actual Outcomes]
        ↓
[Metrics + Weekly Calibration Loop]
```

---

## Services & Ports

| Service | Port | Description |
|---|---|---|
| PostgreSQL | 5432 | Primary structured data store |
| Qdrant | 6333 | Vector database |
| n8n | 5678 | Workflow orchestration |
| PageIndex Service | 8001 | Document segmentation microservice |
| FastAPI App | 8000 | Main API layer |
| Streamlit | 8501 | Consumer Complaint Assistant UI |

> **LLM inference uses external APIs** — no local GPU required.

---

## Quickstart

### Prerequisites
- Docker Desktop
- Python 3.11+
- 16 GB RAM (for all services)

### 1. Clone and configure

```bash
cd "Multi-Agent Financial Complaint Governance Engine"
cp .env.example .env
# Edit .env — set your GROQ_API_KEY
```

### 2. Start infrastructure

```bash
make up
# or: docker compose up -d
```

### 3. Configure LLM provider

Get your free API keys:
- **Groq (Llama 3)**: https://console.groq.com → free, fast, no credit card

Set in `.env`:
```env
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_your-key-here
```

### 4. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 5. Ingest CFPB data

```bash
make ingest
# Fetches 500 Credit Card complaints with narratives
# Segments, embeds, and indexes them in Qdrant
```

### 6. Launch dashboard

```bash
make dashboard
# Opens http://localhost:8501
```

---

## 🚀 HuggingFace Space Deployment

The entire architecture (Qdrant + PageIndex + FastAPI + Streamlit + SQLite) can run inside a **single Docker container** on HuggingFace Spaces.

1. Create a new Docker Space at [huggingface.co/new-space](https://huggingface.co/new-space).
2. Add your `GROQ_API_KEY` to the Space Secrets in settings.
3. Push this repository to your Space:
```bash
git remote add space https://huggingface.co/spaces/<your-username>/<your-space-name>
git push space main
```
The first boot takes ~3 minutes to download the embedding model, initialize the SQLite DB, seed 100 complaints, and index them into Qdrant. Subsequent reboots are instant.

---

## Five-Agent Governance Panel

| Agent | Weight | Focus |
|---|---|---|
| Regulatory Compliance | 30% | CFPB regulations, FCRA/ECOA |
| Fairness | 20% | Disparate impact, protected class |
| Financial Impact | 20% | Monetary harm, billing errors |
| Fraud Pattern | 20% | Unauthorized transactions, evidence |
| Reputation Risk | 10% | Escalation potential, media risk |

### Guardrails (Deterministic Overrides)
- `regulatory_violation_detected = true` → **force Escalate**
- `fraud_score ≥ 8 AND evidence_quality = low` → **force Reject Relief**

### Debate Mechanism
If `std_dev(agent_scores) > DEBATE_THRESHOLD`, a second deliberation round is triggered where agents see each other's reasoning before re-scoring.

---

## Project Structure

```
├── docker-compose.yml
├── .env.example
├── Makefile
├── requirements.txt
├── db/
│   ├── init.sql          # PostgreSQL DDL
│   ├── models.py         # SQLAlchemy ORM
│   └── session.py        # Session factory
├── ingestion/
│   ├── cfpb_fetcher.py   # CFPB API + CSV
│   ├── cleaner.py        # Text normalization
│   ├── loader.py         # PostgreSQL upsert
│   └── run_ingestion.py  # Entry point
├── pageindex/
│   ├── page_parser.py    # Hierarchical segmentation
│   ├── indexer.py        # Persist + embed + Qdrant
│   ├── retriever.py      # Metadata-filtered search
│   ├── context_builder.py# Token-limited context JSON
│   └── Dockerfile
├── embeddings/
│   ├── embedding_service.py  # Local BGE-small
│   └── qdrant_store.py       # Qdrant operations
├── agents/
│   ├── base_agent.py
│   ├── compliance_agent.py
│   ├── fairness_agent.py
│   ├── financial_agent.py
│   ├── fraud_agent.py
│   ├── reputation_agent.py
│   └── aggregator.py
├── api/
│   ├── main.py
│   ├── schemas.py
│   ├── Dockerfile
│   └── routes/
│       ├── complaints.py
│       ├── decisions.py
│       └── metrics.py
├── evaluation/
│   ├── evaluator.py      # Accuracy vs CFPB outcomes
│   └── calibrator.py     # Weekly calibration
├── n8n/
│   ├── ingestion_workflow.json
│   ├── review_workflow.json
│   └── calibration_workflow.json
└── dashboard/
    ├── app.py
    └── pages/
        ├── 1_Complaints.py
        ├── 2_Decision_Detail.py
        ├── 3_Metrics.py
        └── 4_Config.py
```

---

## Decision Outputs & Dynamic Explanations

The system evaluates complaints and recommends one of the following decisions:

| Decision | Meaning |
|---|---|
| **Monetary Relief** | System recommends compensation |
| **Explanation Only** | Company explanation sufficient |
| **Escalate** | Regulatory or fraud concern, human review required |

Instead of hardcoded responses, the agentic backend generates **dynamic, empathetic, and context-aware explanations** for each decision. Acting as a professional company representative, the chatbot provides a tailored summary of the outcome, addressing the specific nuances of the consumer's complaint while strictly adhering to company policy.

---

## Evaluation Metrics

The system compares AI decisions against actual CFPB company responses:
- **Accuracy** — overall agreement rate
- **Precision** — correct relief recommendations / all relief recommendations
- **Recall** — correct relief recommendations / all actual relief cases
- **Dispute Prediction Accuracy** — accuracy on flagged disputed complaints

---

## LLM Configuration

Set in `.env`:

```env
# 'groq' → Llama 3 via Groq API (free tier, fast)
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_your-groq-key
GROQ_MODEL=llama3-70b-8192
```
