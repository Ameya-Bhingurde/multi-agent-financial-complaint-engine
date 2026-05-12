# Multi-Agent Financial Complaint Governance Engine — Implementation Plan

> A production-grade agentic system that ingests real CFPB complaint data, applies hierarchical PageIndex RAG, runs a five-agent governance panel, and produces audit-ready decisions with evaluation against real CFPB outcomes.

---

## Product Definition

> A Multi-Agent Financial Complaint Governance Engine that evaluates consumer complaints using real CFPB resolution data, enforces policy constraints, and produces audit-ready decision recommendations.

**Domain:** Credit Cards  
**Buyer Persona:** Mid-sized bank compliance team · Fintech risk team · RegTech startup

---

## Full System Architecture

```
[CFPB REST API / CSV]
        ↓
[n8n Ingestion Workflow]
        ↓
[PostgreSQL — Structured Complaints]
        ↓
[PageIndex Microservice — Hierarchical Segmentation]
        ↓
[Embedding Service — BGE-small / OpenAI toggle]
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
[5 Parallel LLM Agents — Groq (Llama 3) / OpenAI (GPT-4o) toggle]
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

## What PageIndex Changes vs Naive RAG

| Naive RAG | PageIndex RAG (This System) |
|---|---|
| Flat text chunks | Hierarchical page segments |
| No metadata filtering | Filter by `product`, `issue_type`, `section` |
| Random chunk boundaries | Semantically-aware splits |
| Context may mix topics | Context grouped by complaint document |
| Higher hallucination risk | Reduced hallucination, higher precision |

---

## Database Schema

| Table | Key Columns | Purpose |
|---|---|---|
| `complaints` | `complaint_id`, `product`, `issue`, `narrative`, `company_response`, `disputed_flag`, `date_received` | Raw structured complaint store |
| `document_pages` | `page_id`, `complaint_id`, `section_type`, `text_content`, `metadata_json` | Hierarchical page segments |
| `embeddings` | `page_id`, `qdrant_point_id`, `model_name` | Pointer table — vectors live in Qdrant |
| `agent_votes` | `complaint_id`, `agent_name`, `score`, `confidence`, `reasoning` | Per-agent evaluation results |
| `decisions` | `complaint_id`, `ai_decision`, `ai_confidence`, `actual_outcome`, `agreement_flag` | Final decisions + ground truth |
| `config` | `weight_*`, `debate_threshold`, `cold_start_penalty` | Runtime-configurable parameters |
| `metrics` | `accuracy`, `precision_score`, `recall_score`, `dispute_pred_accuracy` | Evaluation aggregates over time |

---

## Five-Agent Governance Panel

| Agent | Weight | Focus Area |
|---|---|---|
| Regulatory Compliance | 30% | CFPB regulations, FCRA/ECOA, disclosure violations |
| Fairness | 20% | Disparate impact signals, protected class language |
| Financial Impact | 20% | Monetary harm, billing errors, fee disputes |
| Fraud Pattern | 20% | Unauthorized transactions, evidence quality |
| Reputation Risk | 10% | Media exposure risk, escalation potential |

### Aggregation Formula

```
final_score =
  0.30 × compliance_score +
  0.20 × fairness_score   +
  0.20 × financial_score  +
  0.20 × fraud_score      +
  0.10 × reputation_score

confidence = mean(agent_confidences)
             − variance_penalty
             − cold_start_penalty (if < 5 similar cases found)
```

### Guardrails (Deterministic Overrides)

- `regulatory_violation_detected = true` → **force Escalate**
- `fraud_score ≥ 8 AND evidence_quality = low` → **force Reject Relief**

### Debate Mechanism

If `std_dev(agent_scores) > DEBATE_THRESHOLD` → trigger second deliberation round where agents see each other's reasoning before re-scoring.

---

## Phase Roadmap

| Phase | Goal | Status |
|---|---|---|
| **Phase 1** | Scaffold & Infrastructure | ✅ Complete |
| **Phase 2** | Data Ingestion Pipeline (CFPB) | ✅ Complete |
| **Phase 3** | PageIndex RAG Layer + Embeddings | ✅ Complete |
| **Phase 4** | Multi-Agent Engine + FastAPI | ✅ Complete |
| **Phase 5** | Dashboard + Evaluation + n8n Workflows | ✅ Complete |

---

## Deployment Ports

| Service | Port | Purpose |
|---|---|---|
| PostgreSQL | 5432 | Primary structured store |
| Qdrant | 6333 | Vector database |
| n8n | 5678 | Workflow orchestration |
| PageIndex Service | 8001 | Document segmentation microservice |
| FastAPI App | 8000 | Main API layer |
| Streamlit | 8501 | Analyst dashboard |

> **LLM inference is API-based** — no Ollama container. Calls go to Groq (Llama 3) or OpenAI (GPT-4o) depending on `LLM_PROVIDER`.

---

## LLM & Embedding Toggle

All AI components are environment-variable toggled. **No local LLM container** — both providers use external APIs:

```env
# LLM provider: 'groq' (Llama 3, free tier) or 'openai' (GPT-4o)
LLM_PROVIDER=groq

# Groq credentials (Llama 3)
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama3-70b-8192

# OpenAI credentials
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o

# Embeddings: false = local BGE-small, true = OpenAI
USE_OPENAI_EMBEDDINGS=false
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

**Zero code changes** needed to switch providers — only the `.env` file changes.

---

## Why This Design Is Technically Defensible

| Capability | Implementation |
|---|---|
| Agent orchestration | n8n + FastAPI |
| Structured reasoning | JSON schema-enforced agent output |
| Hierarchical retrieval | PageIndex-style document segmentation |
| Deterministic constraints | Guardrail overrides independent of LLM |
| Ground-truth evaluation | CFPB actual outcomes as labels |
| Calibration loop | Weekly drift detection + weight versioning |
| Reproducible deployment | Full Docker Compose + cloud-ready configs |

---

## Deployment Guide

### Option A — Render (Recommended for Full Stack)

Render supports Docker-based deployments and managed PostgreSQL. Best for deploying
the complete backend (FastAPI + PageIndex) with a real database.

**Services to deploy on Render:**

| Render Service Type | What It Runs | Plan |
|---|---|---|
| Web Service (Docker) | `api/Dockerfile` → FastAPI at port 8000 | Starter ($7/mo) |
| Web Service (Docker) | `pageindex/Dockerfile` → PageIndex at port 8001 | Starter ($7/mo) |
| PostgreSQL | Managed PG instance | Free tier or Starter |
| External | Qdrant Cloud (free 1GB cluster) | Free |

**Steps:**

```bash
# 1. Push repo to GitHub
git init && git add . && git commit -m "initial"
git remote add origin https://github.com/your-username/cfpb-engine.git
git push -u origin main

# 2. On Render dashboard → New Web Service → Connect GitHub repo
# 3. Set Build Command: (leave empty, Docker handles it)
# 4. Set Start Command: (leave empty, Dockerfile CMD handles it)
# 5. Add environment variables in Render dashboard:
#    LLM_PROVIDER, GROQ_API_KEY, OPENAI_API_KEY
#    POSTGRES_HOST, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
#    QDRANT_HOST (Qdrant Cloud URL), QDRANT_PORT
#    PAGEINDEX_URL (your PageIndex Render URL)
```

**Render `render.yaml` (Infrastructure as Code):**

```yaml
services:
  - type: web
    name: cfpb-api
    runtime: docker
    dockerfilePath: ./api/Dockerfile
    envVars:
      - key: LLM_PROVIDER
        value: groq
      - key: GROQ_API_KEY
        sync: false    # set in Render dashboard (secret)
      - key: OPENAI_API_KEY
        sync: false
      - key: DATABASE_URL
        fromDatabase:
          name: cfpb-db
          property: connectionString

  - type: web
    name: cfpb-pageindex
    runtime: docker
    dockerfilePath: ./pageindex/Dockerfile

databases:
  - name: cfpb-db
    plan: free
```

---

### Option B — Hugging Face Spaces (Demo / Showcase)

Hugging Face Spaces is best for the **Streamlit dashboard** (Phase 5) as a
public-facing demo. The API backend should still be deployed on Render.

**Steps:**

```bash
# 1. Create a new Space at huggingface.co/spaces
#    SDK: Streamlit | Hardware: CPU Basic (free)

# 2. Add a Space-compatible README.md
cat > README.md << 'EOF'
---
title: CFPB Complaint Governance Engine
emoji: ⚖️
colorFrom: blue
colorTo: indigo
sdk: streamlit
sdk_version: 1.39.0
app_file: dashboard/app.py
pinned: false
---
EOF

# 3. Set Space Secrets (replaces .env for Spaces)
#    Go to Space Settings → Variables and Secrets:
#    API_BASE_URL = https://cfpb-api.onrender.com
#    GROQ_API_KEY = gsk_...
#    OPENAI_API_KEY = sk-...

# 4. Push dashboard code to the Space
git remote add space https://huggingface.co/spaces/your-username/cfpb-engine
git subtree push --prefix dashboard space main
```

**Architecture for deployed version:**

```
[Hugging Face Space — Streamlit Dashboard]
              ↓ HTTP
[Render — FastAPI (cfpb-api.onrender.com)]
              ↓
[Render — PostgreSQL] + [Qdrant Cloud] + [PageIndex on Render]
              ↓ API calls
[Groq API (Llama 3)] or [OpenAI API (GPT-4o)]
```

---

### Environment Variables for Deployment

| Variable | Local Value | Deployed Value |
|---|---|---|
| `POSTGRES_HOST` | `localhost` | Render DB hostname |
| `QDRANT_HOST` | `localhost` | Qdrant Cloud URL |
| `PAGEINDEX_URL` | `http://localhost:8001` | Render PageIndex URL |
| `LLM_PROVIDER` | `groq` | `groq` or `openai` |
| `GROQ_API_KEY` | local key | Render/HF secret |
| `USE_OPENAI_EMBEDDINGS` | `false` | `false` (BGE-small is lightweight enough) |
