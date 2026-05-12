# Phase 1 — Scaffold & Infrastructure

**Status:** ✅ Complete  
**Goal:** Stand up the full Docker environment with all six services healthy, define the complete database schema, and establish the project skeleton.

---

## Overview

Phase 1 establishes everything the rest of the system depends on. No application logic is written here — this phase is purely about making the infrastructure solid, reproducible, and correct before any data or agents are introduced.

The key principle: **every subsequent phase should be independently verifiable** against a running Docker environment created here.

---

## Files Created

```
├── docker-compose.yml
├── .env.example
├── Makefile
├── README.md
├── requirements.txt
└── db/
    ├── __init__.py
    ├── init.sql
    ├── models.py
    └── session.py
```

---

## 1. `docker-compose.yml`

### What it does
Defines and wires together six containerised services that make up the system's infrastructure layer.

### Services

| Service | Image | Port | Role |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | 5432 | Primary relational database |
| `qdrant` | `qdrant/qdrant:latest` | 6333 | Vector store for embeddings |
| `n8n` | `n8nio/n8n:latest` | 5678 | Workflow automation / orchestration |
| `pageindex-service` | Custom (built from `./pageindex/Dockerfile`) | 8001 | Hierarchical document segmentation |
| `fastapi-app` | Custom (built from `./api/Dockerfile`) | 8000 | Main REST API layer |

### Key Design Decisions

**Health checks on every service.**  
Services that depend on others (e.g., `n8n` depends on `postgres`) use `condition: service_healthy` so Docker waits for the upstream service to be fully ready before starting the dependent one. This prevents race conditions during `docker compose up`.

**Shared environment variables via YAML anchors.**  
Database credentials are defined once using a YAML anchor (`x-common-env`) and reused across multiple services. This avoids duplication and ensures all services use the same credentials.

**n8n uses PostgreSQL as its own backing store.**  
Rather than n8n's default SQLite, we configure it to use the same PostgreSQL instance. This keeps everything in one database, simplifies backup, and allows n8n workflows to directly query complaint data.

**Named volumes for persistence.**  
`postgres_data`, `qdrant_data`, and `n8n_data` volumes ensure data survives container restarts. Without these, all indexed vectors and complaint data would be lost on every `docker compose down`.

> **LLM inference is API-based** — no Ollama volume needed. Calls go to Groq (Llama 3) or OpenAI (GPT-4o) via external API.

---

## 2. `.env.example`

### What it does
Provides a complete template of every environment variable the system uses. Developers copy this to `.env` and fill in their values. The `.env` file itself is never committed to version control.

### Variable Groups

**PostgreSQL credentials**
```env
POSTGRES_USER=cfpb
POSTGRES_PASSWORD=cfpb_secret
POSTGRES_DB=complaints_db
```

**LLM toggle** — choose between Groq (Llama 3, free) and OpenAI (GPT-4o) with one variable:
```env
# 'groq' → Llama 3.3 via Groq API (free tier)
# 'openai' → GPT-4o via OpenAI API
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
```

**Embedding toggle** — same principle for embeddings:
```env
USE_OPENAI_EMBEDDINGS=false
# false → BAAI/bge-small-en-v1.5 via sentence-transformers (local, free)
# true  → text-embedding-3-small via OpenAI API
```

**Aggregation parameters** — agent weights sum to 1.0, debate and cold-start thresholds are tunable:
```env
WEIGHT_COMPLIANCE=0.30
WEIGHT_FAIRNESS=0.20
WEIGHT_FINANCIAL=0.20
WEIGHT_FRAUD=0.20
WEIGHT_REPUTATION=0.10
DEBATE_THRESHOLD=2.0
COLD_START_PENALTY=0.15
```

### Why this matters
All tunable parameters are externalised into the environment. There are **zero hardcoded secrets or weights** in the source code. This is critical for both security (secrets management) and operational flexibility (changing agent weights without redeployment).

---

## 3. `db/init.sql`

### What it does
Defines the complete PostgreSQL schema. This file is mounted into the `postgres` container at `/docker-entrypoint-initdb.d/init.sql` so it runs automatically on first startup.

### Tables

#### `complaints`
The primary store for raw CFPB complaint records.

```sql
CREATE TABLE IF NOT EXISTS complaints (
    complaint_id    TEXT PRIMARY KEY,
    product         TEXT NOT NULL,
    sub_product     TEXT,
    issue           TEXT,
    sub_issue       TEXT,
    narrative       TEXT NOT NULL,
    company         TEXT,
    state           TEXT,
    zip_code        TEXT,
    company_response        TEXT,
    timely_response         TEXT,
    consumer_disputed       TEXT,
    disputed_flag           BOOLEAN DEFAULT FALSE,
    date_received           DATE,
    date_sent_to_company    DATE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

Key point: `complaint_id` is a `TEXT` primary key (not an auto-increment integer) because CFPB assigns its own alphanumeric IDs that must be preserved for traceability.

#### `document_pages`
Stores the hierarchical page segments produced by the PageIndex service. One complaint maps to multiple pages.

```sql
CREATE TABLE IF NOT EXISTS document_pages (
    page_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    complaint_id    TEXT NOT NULL REFERENCES complaints(complaint_id) ON DELETE CASCADE,
    page_num        INTEGER NOT NULL DEFAULT 1,
    section_type    TEXT NOT NULL,   -- 'header' | 'narrative' | 'tags'
    text_content    TEXT NOT NULL,
    token_count     INTEGER,
    metadata_json   JSONB DEFAULT '{}'
);
```

The `section_type` column is how the retrieval layer filters results — an agent looking for narrative content can specifically request `section_type = 'narrative'` sections.

#### `embeddings`
A pointer table. The actual vectors live in Qdrant (optimised for ANN search), but this table records which PostgreSQL page corresponds to which Qdrant point.

```sql
CREATE TABLE IF NOT EXISTS embeddings (
    page_id         UUID PRIMARY KEY REFERENCES document_pages(page_id),
    qdrant_point_id TEXT UNIQUE,
    model_name      TEXT NOT NULL,
    vector_dim      INTEGER
);
```

#### `agent_votes`
Records each individual agent's evaluation output for a complaint. Supports multiple rounds (for the debate mechanism).

```sql
CREATE TABLE IF NOT EXISTS agent_votes (
    vote_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    complaint_id    TEXT NOT NULL REFERENCES complaints(complaint_id),
    agent_name      TEXT NOT NULL,
    round_num       INTEGER NOT NULL DEFAULT 1,
    score           NUMERIC(4,2) NOT NULL,
    confidence      NUMERIC(4,3) NOT NULL,
    risk_flags      JSONB DEFAULT '[]',
    reasoning       TEXT,
    raw_response    JSONB
);
```

`round_num` is how the system tracks whether a vote was from the initial round or a debate round. The `raw_response` column stores the complete LLM JSON output for full auditability.

#### `decisions`
One row per complaint. Stores the aggregated final decision and, once known, the actual CFPB outcome for evaluation.

```sql
CREATE TABLE IF NOT EXISTS decisions (
    complaint_id    TEXT UNIQUE NOT NULL REFERENCES complaints(complaint_id),
    final_score     NUMERIC(4,2),
    ai_decision     TEXT,         -- 'Monetary Relief' | 'Explanation Only' | 'Escalate'
    ai_confidence   NUMERIC(4,3),
    debate_rounds   INTEGER DEFAULT 0,
    guardrail_applied TEXT,
    actual_outcome  TEXT,         -- populated by evaluator from CFPB data
    agreement_flag  BOOLEAN       -- did AI match CFPB actual outcome?
);
```

`agreement_flag` is computed by the evaluator (Phase 5) by comparing `ai_decision` against `actual_outcome`. This is the ground-truth feedback loop.

#### `config`
Stores versioned copies of the system's tunable parameters. When the calibrator suggests new weights, a new row is inserted (not an update) so the history of weight changes is preserved.

#### `metrics`
Stores periodic evaluation snapshots (accuracy, precision, recall) so the dashboard can show system performance over time.

---

## 4. `db/models.py`

### What it does
SQLAlchemy ORM models that mirror the `init.sql` schema exactly. Used by all Python components (FastAPI, ingestion scripts, evaluation jobs) to interact with the database in a type-safe way.

### Relationships defined

```
Complaint
  ├── has many DocumentPage (cascade delete)
  │     └── has one Embedding
  ├── has many AgentVote (cascade delete)
  └── has one Decision (cascade delete)
```

### Notable details

- **UUID primary keys** for `document_pages`, `agent_votes`, `decisions`, generated by Python (`uuid.uuid4`) not the database — ensures IDs are available before the INSERT completes.
- **`JSONB` columns** (`risk_flags`, `metadata_json`, `raw_response`) allow structured nested data without schema migrations.
- **`to_dict()` on Config** provides a clean dict export for the API response layer.

---

## 5. `db/session.py`

### What it does
Session factory and connection utilities used across all Python components.

### Two interfaces provided

**`get_db()` — FastAPI dependency injection:**
```python
@app.get("/complaints")
def list_complaints(db: Session = Depends(get_db)):
    ...
```
Yields a session per request and closes it automatically when the request finishes.

**`db_session()` — context manager for scripts:**
```python
with db_session() as db:
    db.add(some_record)
    # auto-commits on exit, rolls back on exception
```
Used by ingestion scripts, the evaluator, and the calibrator — code that runs outside a web request context.

### Connection pooling
Configured with `pool_size=10, max_overflow=20`. Under normal load, 10 persistent connections are maintained. Bursts up to 30 concurrent connections are handled via overflow. This is appropriate for a single-machine deployment serving a compliance team.

---

## 6. `requirements.txt`

Pinned versions for all Python dependencies. Key groups:

| Group | Libraries |
|---|---|
| API & DB | `fastapi`, `uvicorn`, `sqlalchemy`, `psycopg2-binary`, `alembic` |
| Vectors | `qdrant-client` |
| Embeddings | `sentence-transformers`, `torch`, `transformers` |
| LLM | `openai`, `tiktoken` |
| Dashboard | `streamlit`, `plotly`, `pandas` |
| Evaluation | `scikit-learn` |
| Utilities | `httpx`, `pydantic`, `python-dotenv`, `nltk` |

---

## 7. `Makefile`

Convenience shortcuts for all common operations:

```
make up           → docker compose up -d (with service URL summary)
make down         → docker compose down
make logs         → docker compose logs -f
make ingest       → python ingestion/run_ingestion.py --limit 500
make ingest-full  → python ingestion/run_ingestion.py --limit 0
make eval         → python evaluation/evaluator.py
make calibrate    → python evaluation/calibrator.py
make dashboard    → streamlit run dashboard/app.py
make shell-db     → docker exec -it cfpb_postgres psql ...
make reset-db     → drop + recreate schema (with confirmation prompt)
```

---

## How to Verify Phase 1

After running `docker compose up -d`, run these checks:

```bash
# 1. All 6 services are running and healthy
docker compose ps

# 2. All 7 PostgreSQL tables exist
docker exec cfpb_postgres psql -U cfpb -d complaints_db -c "\dt"

# 3. Qdrant is responding
curl http://localhost:6333/collections

# 4. n8n UI is accessible
curl http://localhost:5678/healthz

# 5. Both LLM providers are configured in .env
cat .env | grep -E 'LLM_PROVIDER|GROQ_API_KEY|OPENAI_API_KEY'
```

Expected: all checks pass, no errors.
