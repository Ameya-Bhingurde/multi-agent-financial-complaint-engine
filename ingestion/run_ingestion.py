"""
Ingestion Entry Point — Multi-Agent Financial Complaint Governance Engine

Orchestrates the full ingestion pipeline:
  fetch → clean → load → page-index → embed → Qdrant

Usage:
    python ingestion/run_ingestion.py --limit 500
    python ingestion/run_ingestion.py --limit 0   # all available
"""

import argparse
import logging
import os
import sys

# Make sure project root is on the path when run directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from ingestion.cfpb_fetcher import fetch_complaints
from ingestion.cleaner import clean_record
from ingestion.loader import load_complaints

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("run_ingestion")


def run(limit: int, skip_index: bool = False) -> None:
    logger.info("=" * 60)
    logger.info("CFPB Ingestion Pipeline Started")
    logger.info(f"  Limit        : {limit or 'unlimited'}")
    logger.info(f"  Skip indexing: {skip_index}")
    logger.info("=" * 60)

    # ── Step 1: Fetch ──────────────────────────────────────────
    logger.info("STEP 1/4 — Fetching complaints from CFPB...")
    raw_stream = fetch_complaints(limit=limit)

    # ── Step 2: Clean ──────────────────────────────────────────
    logger.info("STEP 2/4 — Cleaning & validating narratives...")
    def cleaned_stream():
        skipped = 0
        total = 0
        for record in raw_stream:
            total += 1
            cleaned = clean_record(record)
            if cleaned is None:
                skipped += 1
                continue
            yield cleaned
        logger.info(f"  Cleaned: {total - skipped} / {total} records passed validation")

    # ── Step 3: Load into PostgreSQL ───────────────────────────
    logger.info("STEP 3/4 — Loading complaints into PostgreSQL...")
    complaint_ids = load_complaints(cleaned_stream())
    logger.info(f"  {len(complaint_ids)} complaint(s) loaded/updated in DB.")

    if not complaint_ids:
        logger.warning("No complaints were loaded. Check API connectivity or CSV path.")
        return

    # ── Step 4: PageIndex + Embed ──────────────────────────────
    if skip_index:
        logger.info("STEP 4/4 — Skipping indexing (--skip-index flag set).")
    else:
        logger.info("STEP 4/4 — Indexing complaints via PageIndex service...")
        try:
            from pageindex.indexer import index_complaints
            index_complaints(complaint_ids)
            logger.info(f"  Indexed {len(complaint_ids)} complaints into Qdrant.")
        except ImportError:
            logger.warning("PageIndex indexer not yet available. Run Phase 3 setup first.")
        except Exception as e:
            logger.error(f"Indexing failed: {e}. Structured data is still stored in PostgreSQL.")

    logger.info("=" * 60)
    logger.info("✅ Ingestion complete.")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CFPB Complaint Ingestion Pipeline")
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.getenv("INGEST_LIMIT", "500")),
        help="Max complaints to ingest (0 = unlimited)"
    )
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Skip PageIndex/Qdrant step (load to PostgreSQL only)"
    )
    args = parser.parse_args()
    run(limit=args.limit, skip_index=args.skip_index)
