"""
Complaint Loader — Multi-Agent Financial Complaint Governance Engine

Upserts cleaned complaint records into the PostgreSQL complaints table.
"""

import logging
from datetime import date
from typing import Iterator

from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import Complaint
from db.session import db_session

logger = logging.getLogger(__name__)


def _parse_date(value: str) -> date | None:
    """Parse CFPB date strings like '2023-01-15' or '01/15/2023'."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def load_complaints(records: Iterator[dict]) -> list[str]:
    """
    Upsert a stream of cleaned record dicts into the complaints table.
    Returns list of complaint_ids that were newly inserted (not updated).
    """
    inserted_ids = []
    batch = []
    BATCH_SIZE = 100

    def _flush(batch: list[dict]) -> list[str]:
        if not batch:
            return []
        with db_session() as db:
            stmt = pg_insert(Complaint).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["complaint_id"],
                set_={
                    "narrative":        stmt.excluded.narrative,
                    "company_response": stmt.excluded.company_response,
                    "disputed_flag":    stmt.excluded.disputed_flag,
                },
            )
            db.execute(stmt)
        logger.info(f"Flushed batch of {len(batch)} complaints to DB.")
        return [r["complaint_id"] for r in batch]

    for record in records:
        row = {
            "complaint_id":         record["complaint_id"],
            "product":              record["product"],
            "sub_product":          record.get("sub_product"),
            "issue":                record.get("issue"),
            "sub_issue":            record.get("sub_issue"),
            "narrative":            record["narrative"],
            "company":              record.get("company"),
            "state":                record.get("state"),
            "zip_code":             record.get("zip_code"),
            "company_response":     record.get("company_response"),
            "timely_response":      record.get("timely_response"),
            "consumer_disputed":    record.get("consumer_disputed"),
            "disputed_flag":        record.get("disputed_flag", False),
            "date_received":        _parse_date(record.get("date_received", "")),
            "date_sent_to_company": _parse_date(record.get("date_sent_to_company", "")),
        }
        batch.append(row)

        if len(batch) >= BATCH_SIZE:
            inserted_ids.extend(_flush(batch))
            batch = []

    # Flush remainder
    inserted_ids.extend(_flush(batch))
    return inserted_ids
