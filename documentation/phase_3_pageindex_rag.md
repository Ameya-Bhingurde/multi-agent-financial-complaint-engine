# Phase 3 — PageIndex RAG Layer + Embeddings

**Status:** ✅ Complete  
**Goal:** Segment every ingested complaint into a hierarchical document structure, embed each segment, and store it in Qdrant with rich metadata — enabling fast, metadata-filtered retrieval for the LLM agents in Phase 4.

---

## Overview

Phase 3 is the intelligence layer between raw complaints and the LLM agents. It answers a fundamental question:

> *"When an agent needs to understand how similar complaints were resolved in the past, how do we give it the most relevant context without overwhelming its token limit?"*

The answer is **hierarchical document-aware RAG** (Retrieval-Augmented Generation), implemented as a standalone FastAPI microservice.

### Why Not Naive RAG?

| Naive RAG | Phase 3 PageIndex RAG |
|---|---|
| Embed full complaint as one flat blob | Split into header + narrative chunks + tags |
| No metadata filtering | Filter by `product`, `section_type` in Qdrant |
| Random chunk boundaries (fixed char count) | Sentence-boundary-aware splits |
| Context may mix unrelated complaints | Hits grouped by `complaint_id` |
| No cold-start handling | Explicit cold-start flag + confidence penalty |
| Policy knowledge from LLM training only | Injected CFPB policy excerpts per issue type |

---

## Files Created

```
embeddings/
├── __init__.py
├── embedding_service.py
└── qdrant_store.py

pageindex/
├── __init__.py
├── page_parser.py
├── indexer.py
├── retriever.py
├── context_builder.py
├── service.py
└── Dockerfile
```

---

## 1. `embeddings/embedding_service.py`

### What it does
Converts text into dense vector representations. Supports two backends toggled by a single environment variable.

### Dual-Mode Architecture

| Mode | Model | Dimension | Toggled by |
|---|---|---|---|
| **Local (default)** | `BAAI/bge-small-en-v1.5` via `sentence-transformers` | 384 | `USE_OPENAI_EMBEDDINGS=false` |
| **OpenAI** | `text-embedding-3-small` | 1536 | `USE_OPENAI_EMBEDDINGS=true` |

### Design Decisions

**Lazy loading.** The local model (~90MB) is not loaded at import time — only when the first embedding call is made. This keeps startup time fast and avoids loading a model that may not be needed if using the OpenAI backend.

**BGE retrieval prefix.** BGE models are asymmetric — they perform better when query text is prefixed with a task description:
```python
f"Represent this financial complaint for retrieval: {text}"
```
This is applied automatically in local mode.

**Batch support.** `embed_batch(texts)` encodes a list of strings in one model call, which is 10–50× faster than calling `embed_text()` in a loop. The indexer uses this for all page segments of a complaint.

---

## 2. `embeddings/qdrant_store.py`

### What it does
Manages the Qdrant collection lifecycle and all vector operations: collection creation, batched upsert, metadata-filtered search.

### Collection Design

**Payload indexes** are created for four fields at collection creation time:

| Field | Type | Purpose |
|---|---|---|
| `product` | KEYWORD | Filter complaints by product category |
| `issue` | KEYWORD | Filter by complaint issue type |
| `section_type` | KEYWORD | Retrieve only `narrative` sections (not headers) |
| `complaint_id` | KEYWORD | Group segments back to their complaint |

Without payload indexes, Qdrant must scan all vectors to apply filters. With indexes, filtering happens before the ANN search — this is critical at scale (100k+ vectors).

### Qdrant Point Payload Schema

Each stored vector carries this payload:
```json
{
  "complaint_id":     "19356376",
  "page_num":         2,
  "section_type":     "narrative",
  "product":          "Credit card",
  "issue":            "Problem with a purchase shown on your statement",
  "company_response": "Closed with explanation",
  "resolution":       "Closed with explanation",
  "disputed":         false,
  "text_snippet":     "Back in 2020 I made purchases with..."
}
```

The `text_snippet` (first 200 chars) is stored in the payload so the retriever can return preview text without querying PostgreSQL again.

### Search Function

```python
search(
    query_vector   = [...],   # the query complaint's embedding
    top_k          = 5,
    product_filter = "Credit card",
    section_filter = "narrative",   # only narrative sections
)
```

Returns hits sorted by cosine similarity, each with `{id, score, payload}`.

---

## 3. `pageindex/page_parser.py`

### What it does
Transforms a raw complaint narrative into a structured list of page segment dicts. This is the core of the **PageIndex** concept: treating each complaint as a structured document rather than a flat string.

### Document Structure

```
Complaint Document
├── Page 1: "header"
│     Product: Credit card
│     Issue: Billing dispute
│     Date Received: 2026-02-09
│     Company Response: Closed with explanation
│
├── Page 2: "narrative" (chunk 1, ≤ 512 tokens)
│     "Back in 2020 I made purchases with..."
│
├── Page 3: "narrative" (chunk 2, if narrative is long)
│     "...I called Citi bank to dispute after..."
│
└── Page N: "tags"
      Tags: billing_dispute, credit_card, problem_with_purchase
```

### Narrative Splitting Logic

Target: ≤ 512 tokens per chunk (≈ 2048 characters using 4 chars/token estimate).

Algorithm:
1. Split text on sentence boundaries (`.`, `!`, `?` followed by whitespace)
2. Greedily accumulate sentences until the limit is reached
3. If a single sentence exceeds the limit, hard-split at character boundary

This keeps semantic units (sentences) intact rather than cutting mid-sentence.

### Keyword Tag Extraction

The tags page contains domain-relevant tags computed by matching against a keyword dictionary:

| Tag | Detected When Narrative Contains |
|---|---|
| `billing_dispute` | "dispute", "charge", "billing", "statement" |
| `fraud` | "fraud", "unauthorized", "stolen", "identity theft" |
| `payment_issue` | "payment", "late fee", "missed", "autopay" |
| `account_closure` | "closed", "terminat", "cancel" |
| `interest_fees` | "interest", "apr", "rate", "fee" |
| `credit_reporting` | "credit report", "bureau", "equifax" |
| `investigation_failed` | "investigation", "30 days", "unresolved" |

Tags drive the policy excerpt selection in the context builder.

---

## 4. `pageindex/indexer.py`

### What it does
Orchestrates the full pipeline for a single complaint: DB fetch → parse → batch embed → persist → Qdrant upsert.

### Indexing Pipeline (per complaint)

```
PostgreSQL: fetch Complaint row
        ↓
page_parser.parse_complaint()
        ↓
embedding_service.embed_batch([page1_text, page2_text, ...])
        ↓
PostgreSQL: DELETE existing document_pages rows (re-index safe)
PostgreSQL: INSERT DocumentPage rows + Embedding pointer rows
        ↓
qdrant_store.upsert_vectors([{id, vector, payload}, ...])
```

### Re-Index Safety

Before writing new pages, the indexer deletes any existing `document_pages` rows for that `complaint_id` (cascade deletes the `embeddings` pointer rows too). This ensures re-running the indexer doesn't create duplicate pages.

### Batch Mode

`index_complaints(complaint_ids)` calls `index_complaint()` for each ID, logs progress every 50 complaints, catches and counts errors without stopping the batch, and returns a summary:
```json
{"total_indexed": 486, "total_pages": 1943, "errors": 0}
```

---

## 5. `pageindex/retriever.py`

### What it does
Takes an incoming complaint text and retrieves the most semantically similar past cases from Qdrant, grouped by complaint document.

### Retrieval Logic

```
1. embed_text(complaint_text) → query_vector [384 or 1536 dims]
        ↓
2. qdrant_store.search(
       query_vector   = query_vector,
       top_k          = top_k × 3,     ← over-fetch to allow grouping
       product_filter = "Credit card",
       section_filter = "narrative",
   )
        ↓
3. Group hits by complaint_id
   For each group:
     - collect all matching segments
     - track max similarity score
     - keep product, issue, resolution, disputed flag
        ↓
4. Sort groups by max_score DESC
5. Take top_k groups
        ↓
6. Return {cases, cold_start, total_found}
```

### Cold Start Detection

If fewer than `MIN_SIMILAR_CASES` (default: 5) similar cases are found, `cold_start=True` is returned. The context builder adds a warning note and the aggregator applies a confidence penalty.

### Historical Relief Rate

`get_historical_relief_rate()` scrolls through a sample of `header` sections in Qdrant and counts what fraction had `"monetary"` in their `company_response` payload. Returns a float like `0.62`, which gets included in the agent context.

---

## 6. `pageindex/context_builder.py`

### What it does
Compresses retrieval results + complaint metadata into a single structured JSON object that gets passed verbatim to every LLM agent.

### Output Schema

```json
{
  "complaint_text":          "Consumer's narrative (≤6000 chars)...",
  "product":                 "Credit card",
  "issue":                   "Problem with a purchase shown on your statement",
  "retrieved_cases": [
    {
      "rank":          1,
      "complaint_id":  "19284619",
      "product":       "Credit card",
      "issue":         "Problem with a purchase shown on your statement",
      "resolution":    "Closed with explanation",
      "disputed":      false,
      "similarity":    0.9134,
      "snippet":       "On 01/15/2024 I disputed a credit card charge..."
    }
  ],
  "total_similar_found":     5,
  "cold_start":              false,
  "policy_excerpt":          "CFPB Regulation Z (12 C.F.R. § 1026.13): ...",
  "historical_relief_rate":  0.173
}
```

### Policy Excerpt Selection

Automatically selects the most relevant CFPB policy based on issue text and keyword tags:

| Matched Signal | Policy Injected |
|---|---|
| "billing", "dispute", "statement" | Regulation Z — 30/90 day dispute resolution |
| "fraud", "unauthorized", "stolen" | FCBA/EFTA — $50 liability cap, provisional credit |
| "closed", "terminat" | ECOA/Reg B — adverse action notice, deposit return |
| "credit report", "bureau" | FCRA — 30-day investigation, furnisher duty |
| "interest", "apr", "fee" | CARD Act — retroactive rate increase prohibition |
| (default) | General CFPB complaint response standard |

This eliminates the need for agents to retrieve policy from their training data, reducing hallucination risk.

---

## 7. `pageindex/service.py` — FastAPI Microservice

### What it does
Wraps all PageIndex functionality as a REST API running at port 8001.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `GET` | `/stats` | Qdrant collection stats |
| `POST` | `/parse` | Parse complaint → page segments (no DB write) |
| `POST` | `/index/{id}` | Index one complaint (fetch PG → embed → Qdrant) |
| `POST` | `/index/batch` | Batch index list of complaint IDs |
| `POST` | `/retrieve` | Retrieve similar cases |
| `POST` | `/context` | Build full agent context JSON |

The `/context` endpoint is the one called by the FastAPI app's decision endpoint (Phase 4) before agent execution.

---

## End-to-End Phase 3 Data Flow

```
[run_ingestion.py]
  → complaints loaded into PostgreSQL
                ↓
[pageindex/indexer.py] (called per complaint)
  → fetch Complaint from PostgreSQL
  → page_parser: split into header + narrative chunks + tags
  → embedding_service: embed_batch([page texts])
  → PostgreSQL: INSERT document_pages + embeddings rows
  → qdrant_store: upsert_vectors with metadata payload
                ↓
[Qdrant cfpb_pages collection]
  → vectors stored with product, issue, section_type, snippet payloads
  → payload indexes: product, issue, section_type, complaint_id

---------------------------------------------------------
Complaint evaluation triggered (Phase 4 → this layer)

[pageindex/retriever.py]
  → embed incoming complaint text
  → Qdrant filtered search (product + section=narrative)
  → group hits by complaint_id → rank by max similarity → cold start check
                ↓
[pageindex/context_builder.py]
  → format top-K cases (rank, resolution, similarity, snippet)
  → inject CFPB policy excerpt (auto-selected by issue type)
  → include historical relief rate
  → return structured JSON ≤ 6000 chars
                ↓
[Agents in Phase 4]
  → receive context JSON
  → reason over complaint + similar cases + policy
  → return structured score JSON
```

---

## How to Verify Phase 3

```bash
# 1. Run ingestion with indexing enabled (no --skip-index flag)
python ingestion/run_ingestion.py --limit 20

# 2. Check Qdrant collection has vectors
curl http://localhost:6333/collections/cfpb_pages
# Expected: "vectors_count": 60+ (≈3 pages per complaint × 20 complaints)

# 3. Test the PageIndex microservice
curl http://localhost:8001/health
# Expected: {"status": "ok", "qdrant": true}

curl http://localhost:8001/stats
# Expected: {"vectors_count": 60, "points_count": 60, "status": "green"}

# 4. Test retrieval
curl -X POST http://localhost:8001/retrieve \
  -H "Content-Type: application/json" \
  -d '{
    "complaint_text": "I disputed a charge on my credit card and the bank never responded within 30 days",
    "product": "Credit card",
    "top_k": 3
  }'
# Expected: JSON with "cases" list and "cold_start": false

# 5. Test full context build
curl -X POST http://localhost:8001/context \
  -H "Content-Type: application/json" \
  -d '{
    "complaint_text": "My bank charged me unauthorized fees and never responded to my dispute.",
    "product": "Credit card",
    "issue": "Billing dispute"
  }'
# Expected: full context JSON with policy_excerpt, retrieved_cases, historical_relief_rate
```

Expected: all checks pass, policy excerpt is relevant, retrieved cases are real CFPB complaints.
