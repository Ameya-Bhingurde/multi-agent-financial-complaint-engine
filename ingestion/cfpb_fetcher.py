"""
CFPB Data Fetcher — Multi-Agent Financial Complaint Governance Engine

Fetches Credit Card complaints with consumer narratives from the
CFPB public REST API. Falls back to CSV if CFPB_CSV_PATH is set.
"""

import csv
import io
import logging
import os
import time
from typing import Iterator

import requests

logger = logging.getLogger(__name__)

CFPB_API_BASE = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
DEFAULT_PAGE_SIZE = 100


def _build_params(page_size: int, from_index: int) -> dict:
    return {
        "product":      "Credit card",
        "has_narrative": "true",
        "size":         page_size,
        "from":         from_index,
        "sort":         "created_date_desc",
    }


def fetch_from_api(limit: int = 500) -> Iterator[dict]:
    """
    Paginate through the CFPB API and yield raw complaint dicts.
    limit=0 means fetch all available.
    """
    fetched = 0
    from_index = 0
    page_size = min(DEFAULT_PAGE_SIZE, limit) if limit > 0 else DEFAULT_PAGE_SIZE

    logger.info(f"Starting CFPB API fetch (limit={limit or 'unlimited'})")

    while True:
        params = _build_params(page_size, from_index)
        try:
            resp = requests.get(CFPB_API_BASE, params=params, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"CFPB API request failed: {e}")
            break

        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            logger.info("No more complaints returned by API.")
            break

        for hit in hits:
            src = hit.get("_source", {})
            yield _normalize_api_record(src)
            fetched += 1
            if limit > 0 and fetched >= limit:
                logger.info(f"Reached limit of {limit} complaints.")
                return

        from_index += page_size
        logger.info(f"Fetched {fetched} complaints so far...")
        time.sleep(0.3)  # polite rate limit


def _normalize_api_record(src: dict) -> dict:
    """Map CFPB API field names to our schema field names."""
    return {
        "complaint_id":         str(src.get("complaint_id", "")),
        "product":              src.get("product", ""),
        "sub_product":          src.get("sub_product", ""),
        "issue":                src.get("issue", ""),
        "sub_issue":            src.get("sub_issue", ""),
        "narrative":            src.get("complaint_what_happened", ""),
        "company":              src.get("company", ""),
        "state":                src.get("state", ""),
        "zip_code":             src.get("zip_code", ""),
        "company_response":     src.get("company_response", ""),
        "timely_response":      src.get("timely", ""),
        "consumer_disputed":    src.get("consumer_disputed", ""),
        "date_received":        src.get("date_received", ""),
        "date_sent_to_company": src.get("date_sent_to_company", ""),
    }


def fetch_from_csv(csv_path: str, limit: int = 500) -> Iterator[dict]:
    """
    Read complaints from a local CFPB CSV file.
    Filters for Credit Card product and non-empty narrative.
    """
    logger.info(f"Reading CFPB CSV from {csv_path}")
    fetched = 0

    with open(csv_path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            product = row.get("Product", "")
            narrative = row.get("Consumer complaint narrative", "")

            if "credit card" not in product.lower():
                continue
            if not narrative or len(narrative.strip()) < 50:
                continue

            yield _normalize_csv_record(row)
            fetched += 1
            if limit > 0 and fetched >= limit:
                logger.info(f"Reached CSV limit of {limit}.")
                return


def _normalize_csv_record(row: dict) -> dict:
    """Map CFPB CSV column names to our schema field names."""
    return {
        "complaint_id":         str(row.get("Complaint ID", "")),
        "product":              row.get("Product", ""),
        "sub_product":          row.get("Sub-product", ""),
        "issue":                row.get("Issue", ""),
        "sub_issue":            row.get("Sub-issue", ""),
        "narrative":            row.get("Consumer complaint narrative", ""),
        "company":              row.get("Company", ""),
        "state":                row.get("State", ""),
        "zip_code":             row.get("ZIP code", ""),
        "company_response":     row.get("Company response to consumer", ""),
        "timely_response":      row.get("Timely response?", ""),
        "consumer_disputed":    row.get("Consumer disputed?", ""),
        "date_received":        row.get("Date received", ""),
        "date_sent_to_company": row.get("Date sent to company", ""),
    }


def fetch_complaints(limit: int = 500) -> Iterator[dict]:
    """
    Top-level entry point. Uses CSV if CFPB_CSV_PATH is set, else API.
    """
    csv_path = os.getenv("CFPB_CSV_PATH", "")
    if csv_path and os.path.exists(csv_path):
        yield from fetch_from_csv(csv_path, limit)
    else:
        yield from fetch_from_api(limit)
