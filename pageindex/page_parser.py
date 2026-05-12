"""
PageIndex Page Parser — Multi-Agent Financial Complaint Governance Engine

Hierarchically segments a complaint document into structured pages:

  Complaint Document
  ├── section: "header"    → product, issue, date metadata (always 1 segment)
  ├── section: "narrative" → body text split at ≤ 512 tokens per segment
  └── section: "tags"      → computed keyword tags (always 1 segment)

Returns a list of page dicts ready for the indexer.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

MAX_NARRATIVE_TOKENS = 512   # approximate target per narrative chunk
AVG_CHARS_PER_TOKEN  = 4     # rough char→token estimate without a tokenizer


def _char_limit() -> int:
    return MAX_NARRATIVE_TOKENS * AVG_CHARS_PER_TOKEN   # 2048 chars ≈ 512 tokens


def _split_narrative(text: str) -> list[str]:
    """
    Split narrative into chunks ≤ MAX_NARRATIVE_TOKENS tokens.
    Splits on sentence boundaries where possible.
    """
    limit = _char_limit()
    if len(text) <= limit:
        return [text]

    # Split on sentence endings
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks, current = [], ""

    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= limit:
            current = (current + " " + sentence).strip() if current else sentence
        else:
            if current:
                chunks.append(current)
            # Handle very long single sentences by hard-splitting
            if len(sentence) > limit:
                for i in range(0, len(sentence), limit):
                    chunks.append(sentence[i : i + limit])
                current = ""
            else:
                current = sentence

    if current:
        chunks.append(current)

    return chunks


def _extract_keywords(text: str, product: str, issue: str) -> list[str]:
    """
    Extract a small set of domain-relevant keyword tags from the complaint text.
    Used for the 'tags' page segment.
    """
    keywords = set()

    # Domain keyword dictionary
    domains = {
        "billing_dispute":      ["dispute", "charge", "billing", "statement", "overcharged"],
        "fraud":                ["fraud", "unauthorized", "stolen", "identity theft", "fraudulent"],
        "payment_issue":        ["payment", "due", "late fee", "missed", "autopay"],
        "account_closure":      ["closed", "account closed", "cancel", "termination"],
        "interest_fees":        ["interest", "apr", "rate", "fee", "charged"],
        "credit_reporting":     ["credit report", "credit score", "bureau", "equifax", "experian", "transunion"],
        "rewards":              ["rewards", "points", "cashback", "miles", "benefit"],
        "customer_service":     ["customer service", "representative", "hold", "no response", "ignored"],
        "investigation_failed": ["investigation", "30 days", "unresolved", "no answer", "pending"],
    }

    text_lower = text.lower()
    for tag, terms in domains.items():
        if any(term in text_lower for term in terms):
            keywords.add(tag)

    # Always include product and issue as tags
    if product:
        keywords.add(product.lower().replace(" ", "_"))
    if issue:
        keywords.add(issue.lower().replace(" ", "_").replace(",", ""))

    return sorted(keywords)


def parse_complaint(
    complaint_id: str,
    narrative: str,
    product: str,
    issue: str,
    company_response: str = "",
    date_received: str = "",
    **kwargs: Any,
) -> list[dict]:
    """
    Main entry point. Returns a list of page segment dicts.

    Each dict contains:
      complaint_id, page_num, section_type, text_content, token_count, metadata_json
    """
    pages = []

    # ── Page 1: Header ────────────────────────────────────────────────────
    header_text = (
        f"Product: {product}\n"
        f"Issue: {issue}\n"
        f"Date Received: {date_received}\n"
        f"Company Response: {company_response}"
    ).strip()

    pages.append({
        "complaint_id":  complaint_id,
        "page_num":      1,
        "section_type":  "header",
        "text_content":  header_text,
        "token_count":   len(header_text) // AVG_CHARS_PER_TOKEN,
        "metadata_json": {
            "product":          product,
            "issue":            issue,
            "date_received":    date_received,
            "company_response": company_response,
        },
    })

    # ── Pages 2+: Narrative chunks ────────────────────────────────────────
    narrative_chunks = _split_narrative(narrative)
    for idx, chunk in enumerate(narrative_chunks):
        page_num = 2 + idx
        pages.append({
            "complaint_id":  complaint_id,
            "page_num":      page_num,
            "section_type":  "narrative",
            "text_content":  chunk,
            "token_count":   len(chunk) // AVG_CHARS_PER_TOKEN,
            "metadata_json": {
                "product":          product,
                "issue":            issue,
                "chunk_index":      idx,
                "total_chunks":     len(narrative_chunks),
                "company_response": company_response,
            },
        })

    # ── Last Page: Tags ───────────────────────────────────────────────────
    tags = _extract_keywords(narrative, product, issue)
    tags_text = "Tags: " + ", ".join(tags) if tags else "Tags: general"
    tag_page_num = len(pages) + 1

    pages.append({
        "complaint_id":  complaint_id,
        "page_num":      tag_page_num,
        "section_type":  "tags",
        "text_content":  tags_text,
        "token_count":   len(tags_text) // AVG_CHARS_PER_TOKEN,
        "metadata_json": {
            "product":          product,
            "issue":            issue,
            "tags":             tags,
            "company_response": company_response,
        },
    })

    logger.debug(
        f"Parsed complaint {complaint_id}: "
        f"{len(narrative_chunks)} narrative chunk(s), "
        f"{len(pages)} total pages."
    )
    return pages
