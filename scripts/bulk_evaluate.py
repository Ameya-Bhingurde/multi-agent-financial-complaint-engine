"""
Bulk Evaluation Script — evaluates all pending complaints in batches of 50.
Queries DB directly for complaint IDs (bypasses API 200-limit),
then evaluates via API with rate limiting between calls.
"""
import os, sys, time, logging
sys.path.insert(0, ".")
from dotenv import load_dotenv; load_dotenv()

import httpx
from db.session import SessionLocal
from db.models import Complaint, Decision

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
logger = logging.getLogger("bulk_eval")

API_BASE    = "http://localhost:8000"
BATCH_SIZE  = 50     # complaints per batch
SLEEP_CALL  = 2.0    # seconds between individual calls (~30/min, within Groq limit)
SLEEP_BATCH = 8.0    # extra pause between batches


def get_pending_ids() -> list[str]:
    db = SessionLocal()
    try:
        decided = {r.complaint_id for r in db.query(Decision.complaint_id).all()}
        all_ids = [r.complaint_id for r in db.query(Complaint.complaint_id).all()]
        return [cid for cid in all_ids if cid not in decided]
    finally:
        db.close()


def evaluate_one(cid: str) -> dict:
    r = httpx.post(f"{API_BASE}/evaluate/{cid}", timeout=120)
    r.raise_for_status()
    return r.json()


def main():
    pending = get_pending_ids()
    total   = len(pending)
    logger.info(f"Found {total} pending complaints.")

    if total == 0:
        logger.info("All complaints already evaluated!"); return

    batches = [pending[i:i+BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    logger.info(f"Running {len(batches)} batches of {BATCH_SIZE}.")

    success, failed, done = 0, 0, 0

    for b_num, batch in enumerate(batches, 1):
        logger.info(f"\n── Batch {b_num}/{len(batches)} ({len(batch)} complaints) ──")
        for cid in batch:
            done += 1
            try:
                d = evaluate_one(cid)
                logger.info(f"  [{done}/{total}] {cid} → {d.get('ai_decision')} (conf:{d.get('ai_confidence',0):.2f})")
                success += 1
            except Exception as e:
                logger.error(f"  [{done}/{total}] {cid} FAILED: {e}")
                failed += 1
            time.sleep(SLEEP_CALL)

        if b_num < len(batches):
            logger.info(f"  Batch {b_num} done. Pausing {SLEEP_BATCH}s...")
            time.sleep(SLEEP_BATCH)

    logger.info(f"\n{'='*50}")
    logger.info(f"✅ Done: {success} success, {failed} failed / {total} total.")


if __name__ == "__main__":
    main()
