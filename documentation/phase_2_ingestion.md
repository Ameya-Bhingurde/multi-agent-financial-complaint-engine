# Phase 2 — Data Ingestion Pipeline

**Status:** ✅ Complete  
**Goal:** Fetch real CFPB Credit Card complaints with consumer narratives, clean them, and load them into PostgreSQL with deduplication. Also trigger the PageIndex indexing pipeline once Phase 3 is available.

---

## Overview

Phase 2 is the system's data foundation. Without real complaint data, no agent can produce meaningful evaluations. This phase implements a production-quality ingestion pipeline that:

1. Pulls data from the **CFPB public REST API** (or a local CSV as fallback)
2. Filters for **Credit Card complaints with consumer narratives only**
3. **Redacts PII** and validates text quality
4. **Upserts** into PostgreSQL with safe conflict handling
5. Triggers **PageIndex + embedding** (once Phase 3 is in place)

The pipeline is designed to be **idempotent** — running it multiple times will not create duplicate records.

---

## Files Created

```
ingestion/
├── __init__.py
├── cfpb_fetcher.py
├── cleaner.py
├── loader.py
└── run_ingestion.py
```

---

## Data Source: CFPB Consumer Complaint Database

The Consumer Financial Protection Bureau (CFPB) maintains a public database of consumer complaints submitted against financial companies. The data is fully open and accessible via:

- **REST API:** `https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/`
- **CSV Download:** Available from the same portal

Each complaint record contains:
- `complaint_id` — unique identifier assigned by CFPB
- `product` — e.g., "Credit card", "Mortgage"
- `issue` / `sub_issue` — categorised problem type
- `complaint_what_happened` — the consumer's own narrative (optional)
- `company_response` — the company's resolution (e.g., "Monetary relief", "Explanation provided")
- `consumer_disputed` — whether the consumer disputed the resolution

> The `company_response` field is used as **ground truth** in Phase 5's evaluation module to measure whether the AI's decision aligned with the actual outcome.

---

## 1. `ingestion/cfpb_fetcher.py`

### What it does
Fetches complaint records from the CFPB API using pagination, normalises the field names to the project's schema, and streams records as Python dicts. Falls back to a local CSV file if `CFPB_CSV_PATH` is set in the environment.

### API Strategy

The CFPB API returns results in pages. The fetcher uses `from` (offset) and `size` (page size) parameters to paginate:

```python
params = {
    "product":       "Credit card",
    "has_narrative": "true",
    "size":          100,
    "from":          0,
    "sort":          "created_date_desc",
}
```

Key parameters:
- `product=Credit card` — restricts to Credit Card domain only
- `has_narrative=true` — only complaints where the consumer wrote their own account; narratives are essential for the LLM agents to reason over
- `sort=created_date_desc` — most recent complaints first, so the system has current data

Pagination continues until:
- The API returns an empty `hits` array (no more data), or
- The `--limit` count is reached

A polite `time.sleep(0.3)` delay is added between requests to avoid hammering the public API.

### CSV Fallback

For offline development or when a pre-downloaded dataset is available:

```env
CFPB_CSV_PATH=/path/to/complaints.csv
```

The CSV reader applies the same product/narrative filters as the API fetcher and maps CFPB CSV column names to the internal schema names.

### Field Normalisation

Both the API response and CSV have different field names for the same data. Both paths normalise to the same internal schema:

| Internal Field | API Field | CSV Column |
|---|---|---|
| `complaint_id` | `complaint_id` | `Complaint ID` |
| `narrative` | `complaint_what_happened` | `Consumer complaint narrative` |
| `company_response` | `company_response` | `Company response to consumer` |
| `issue` | `issue` | `Issue` |

This means the rest of the pipeline only ever sees one consistent format, regardless of data source.

---

## 2. `ingestion/cleaner.py`

### What it does
Validates and cleans each complaint narrative before it enters the database. Returns `None` for records that fail validation so they are silently skipped.

### Cleaning Pipeline

```
raw narrative
    ↓
redact_pii()          → replace credit card numbers, SSNs, phones, emails, ZIPs
    ↓
strip_boilerplate()   → remove common CFPB form phrases
    ↓
normalize_whitespace()→ collapse multiple newlines/spaces
    ↓
length check          → discard if < 50 chars (not meaningful)
    ↓
truncate              → cap at 10,000 chars (~2,500 tokens) to avoid token overflow
    ↓
clean narrative
```

### PII Redaction Patterns

The cleaner uses regex to replace sensitive data with placeholder tokens:

| Pattern | Regex | Replacement |
|---|---|---|
| Credit card numbers (16-digit) | `\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b` | `[ACCOUNT_NUMBER]` |
| Social Security Numbers | `\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b` | `[SSN]` |
| Phone numbers | US format with optional country code | `[PHONE]` |
| Email addresses | Standard email regex | `[EMAIL]` |
| ZIP codes | 5-digit or ZIP+4 | `[ZIP]` |

> Note: CFPB already redacts some PII before publishing (you'll see `XXXX` placeholders in narratives). This layer catches anything that slips through and ensures no PII reaches the LLM agents.

### Boilerplate Stripping

Common CFPB complaint form phrases add noise without signal:

```python
_BOILERPLATE = [
    r"I am writing to file a complaint",
    r"Please investigate this matter",
    r"Thank you for your assistance",
    r"XX+",   # CFPB's own redaction placeholders
]
```

These are stripped so LLM agents focus on the substantive complaint content.

### Validation Rules

| Rule | Detail |
|---|---|
| Minimum length | 50 characters after cleaning |
| Maximum length | 10,000 characters (truncated with `...`) |
| Non-empty `complaint_id` | Records without an ID are silently rejected |

### `clean_record()` — Full Record Cleaner

In addition to the narrative, `clean_record()` also:
- Computes `disputed_flag` as a boolean from the `consumer_disputed` string (`"Yes"` → `True`)
- Strips whitespace from `product`, `issue`, and `company_response` fields

---

## 3. `ingestion/loader.py`

### What it does
Takes a stream of cleaned complaint dicts and upserts them into the PostgreSQL `complaints` table in batches of 100 records.

### Upsert Strategy

Rather than a plain `INSERT`, the loader uses PostgreSQL's `INSERT ... ON CONFLICT DO UPDATE`:

```python
stmt = pg_insert(Complaint).values(batch)
stmt = stmt.on_conflict_do_update(
    index_elements=["complaint_id"],
    set_={
        "narrative":        stmt.excluded.narrative,
        "company_response": stmt.excluded.company_response,
        "disputed_flag":    stmt.excluded.disputed_flag,
    },
)
```

**Why this matters:**  
If the pipeline is re-run (e.g., after fetching updated data), complaints that already exist are updated with their new narrative and response values rather than raising a duplicate key error. This makes the ingestion pipeline **fully idempotent**.

Fields that are **not** updated on conflict (e.g., `date_received`, `company`, `state`) are assumed to be stable identifiers that shouldn't change for an existing complaint.

### Batch Size
Records are accumulated into batches of 100 and flushed to the database together. This:
- Reduces the number of round-trips to PostgreSQL significantly
- Keeps memory usage bounded (only 100 records in memory at a time)
- Allows the remainder to be flushed after the stream ends

### Date Parsing
CFPB dates come in inconsistent formats across API vs CSV. The loader's `_parse_date()` function tries multiple formats:
```python
for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
    ...
```
Returns `None` if no format matches (rather than crashing).

---

## 4. `ingestion/run_ingestion.py`

### What it does
The single entry point for the entire ingestion pipeline. Orchestrates all steps in sequence and provides clear logging for each stage.

### Pipeline Steps

```
STEP 1/4 — Fetch complaints from CFPB API (or CSV)
STEP 2/4 — Clean & validate narratives
STEP 3/4 — Upsert into PostgreSQL
STEP 4/4 — Trigger PageIndex + Qdrant indexing   ← runs once Phase 3 is in place
```

Steps 1–3 are implemented in this phase. Step 4 gracefully catches an `ImportError` if Phase 3 hasn't been deployed yet — so the ingestion pipeline can be run and verified independently.

### Usage

```bash
# Ingest 500 Credit Card complaints
python ingestion/run_ingestion.py --limit 500

# Ingest everything available
python ingestion/run_ingestion.py --limit 0

# Load to PostgreSQL only, skip Qdrant indexing
python ingestion/run_ingestion.py --limit 100 --skip-index

# Use environment variable for limit
# Set INGEST_LIMIT=200 in .env
python ingestion/run_ingestion.py
```

### Logging Output

```
2026-02-28 07:30:00 | run_ingestion | INFO | ============================================================
2026-02-28 07:30:00 | run_ingestion | INFO | CFPB Ingestion Pipeline Started
2026-02-28 07:30:00 | run_ingestion | INFO |   Limit        : 500
2026-02-28 07:30:01 | run_ingestion | INFO | STEP 1/4 — Fetching complaints from CFPB...
2026-02-28 07:30:04 | cfpb_fetcher  | INFO | Fetched 100 complaints so far...
2026-02-28 07:30:07 | cfpb_fetcher  | INFO | Fetched 200 complaints so far...
...
2026-02-28 07:30:20 | run_ingestion | INFO | STEP 2/4 — Cleaning & validating narratives...
2026-02-28 07:30:20 | run_ingestion | INFO |   Cleaned: 486 / 500 records passed validation
2026-02-28 07:30:20 | run_ingestion | INFO | STEP 3/4 — Loading complaints into PostgreSQL...
2026-02-28 07:30:21 | ingestion.loader | INFO | Flushed batch of 100 complaints to DB.
...
2026-02-28 07:30:22 | run_ingestion | INFO | 486 complaint(s) loaded/updated in DB.
2026-02-28 07:30:22 | run_ingestion | INFO | STEP 4/4 — Indexing complaints via PageIndex service...
2026-02-28 07:30:25 | run_ingestion | INFO | Indexed 486 complaints into Qdrant.
2026-02-28 07:30:25 | run_ingestion | INFO | ✅ Ingestion complete.
```

---

## End-to-End Data Flow (Phase 2)

```
CFPB REST API
    │
    │  GET /search/api/v1/?product=Credit+card&has_narrative=true&size=100
    │
    ▼
cfpb_fetcher.py
    │  normalise API field names → internal schema
    │  paginate until limit reached
    │
    ▼
cleaner.py
    │  redact PII (account numbers, SSNs, phones, emails)
    │  strip CFPB boilerplate
    │  validate: length ≥ 50 chars
    │  skip invalid → None
    │
    ▼
loader.py
    │  batch = 100 records
    │  INSERT ... ON CONFLICT (complaint_id) DO UPDATE
    │  flush batch → PostgreSQL
    │
    ▼
PostgreSQL → complaints table
    │  complaint_id (PK)
    │  product, issue, narrative, company_response
    │  disputed_flag, date_received
    │
    ▼
[Phase 3 trigger]  ← once PageIndex is available
    │  pageindex/indexer.py
    │  embeddings/qdrant_store.py
    ▼
Qdrant → cfpb_pages collection
```

---

## How to Verify Phase 2

```bash
# 1. Run ingestion with a small limit first
python ingestion/run_ingestion.py --limit 20 --skip-index

# 2. Confirm records in PostgreSQL
docker exec cfpb_postgres psql -U cfpb -d complaints_db \
  -c "SELECT COUNT(*) FROM complaints;"
# Expected: 20 (or close, depending on cleaning rejections)

# 3. Check a sample record
docker exec cfpb_postgres psql -U cfpb -d complaints_db \
  -c "SELECT complaint_id, product, issue, length(narrative) FROM complaints LIMIT 5;"

# 4. Confirm idempotency — re-run the same command, count stays the same
python ingestion/run_ingestion.py --limit 20 --skip-index
docker exec cfpb_postgres psql -U cfpb -d complaints_db \
  -c "SELECT COUNT(*) FROM complaints;"
# Expected: still 20 (no duplicates)

# 5. Check disputed_flag conversion
docker exec cfpb_postgres psql -U cfpb -d complaints_db \
  -c "SELECT disputed_flag, COUNT(*) FROM complaints GROUP BY disputed_flag;"
```

Expected results: records present, no duplicates on re-run, `disputed_flag` as boolean, no raw PII visible in narratives.
