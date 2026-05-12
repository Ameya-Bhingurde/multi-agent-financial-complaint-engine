"""
Text Cleaner — Multi-Agent Financial Complaint Governance Engine

Strips PII patterns, normalizes whitespace, and validates narratives
before they are stored in the database or indexed.
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ─── PII Redaction Patterns ───────────────────────────────────

_PATTERNS = [
    # Account numbers (16-digit sequences, common credit card format)
    (re.compile(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b"), "[ACCOUNT_NUMBER]"),
    # SSN
    (re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"), "[SSN]"),
    # Phone numbers
    (re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"), "[PHONE]"),
    # Email addresses
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    # ZIP codes (standalone)
    (re.compile(r"\b\d{5}(?:-\d{4})?\b"), "[ZIP]"),
]

# Common CFPB boilerplate to strip
_BOILERPLATE = [
    r"I am writing to file a complaint",
    r"Please investigate this matter",
    r"Thank you for your assistance",
    r"XX+",   # CFPB redaction placeholders like XXXX
]
_BOILERPLATE_RE = re.compile("|".join(_BOILERPLATE), re.IGNORECASE)

MIN_NARRATIVE_LENGTH = 50
MAX_NARRATIVE_LENGTH = 10_000  # chars, ~2500 tokens


def redact_pii(text: str) -> str:
    """Replace PII patterns with placeholder tokens."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def strip_boilerplate(text: str) -> str:
    """Remove common CFPB form boilerplate phrases."""
    text = _BOILERPLATE_RE.sub(" ", text)
    return text


def normalize_whitespace(text: str) -> str:
    """Collapse multiple spaces/newlines to single space."""
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def clean_narrative(text: str) -> Optional[str]:
    """
    Full cleaning pipeline for a complaint narrative.
    Returns None if the result is too short to be useful.
    """
    if not text or not text.strip():
        return None

    text = redact_pii(text)
    text = strip_boilerplate(text)
    text = normalize_whitespace(text)

    if len(text) < MIN_NARRATIVE_LENGTH:
        logger.debug(f"Narrative too short after cleaning ({len(text)} chars), skipping.")
        return None

    # Truncate if excessively long
    if len(text) > MAX_NARRATIVE_LENGTH:
        text = text[:MAX_NARRATIVE_LENGTH] + "..."

    return text


def clean_record(record: dict) -> Optional[dict]:
    """
    Clean a full ingestion record. Returns None if narrative is invalid.
    """
    if not record.get("complaint_id"):
        logger.debug("Skipping record with no complaint_id.")
        return None

    cleaned_narrative = clean_narrative(record.get("narrative", ""))
    if cleaned_narrative is None:
        return None

    return {
        **record,
        "narrative":        cleaned_narrative,
        "disputed_flag":    str(record.get("consumer_disputed", "")).strip().lower() == "yes",
        "product":          record.get("product", "").strip(),
        "issue":            record.get("issue", "").strip(),
        "company_response": record.get("company_response", "").strip(),
    }
