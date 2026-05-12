"""
Context Builder — Multi-Agent Financial Complaint Governance Engine

Takes retrieved similar cases + complaint metadata and compresses them
into a token-limited structured JSON context for the LLM agents.

Output format:
{
  "complaint_text":         str,
  "product":                str,
  "issue":                  str,
  "retrieved_cases":        [...],
  "policy_excerpt":         str,
  "historical_relief_rate": float,
  "cold_start":             bool
}
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS   = 6000   # ~1500 tokens — leaves room for agent's own reasoning
MAX_SNIPPET_CHARS   = 300    # per case snippet
MAX_CASES_IN_OUTPUT = 5

# Policy excerpts keyed by issue category keywords
_POLICY_EXCERPTS: dict[str, str] = {
    "billing_dispute": (
        "CFPB Regulation Z (12 C.F.R. § 1026.13): Creditors must acknowledge billing "
        "error notices within 30 days and resolve within 2 billing cycles (max 90 days). "
        "Failure to do so may result in forfeiture of the disputed amount."
    ),
    "fraud": (
        "CFPB guidance on unauthorized transactions: Under the Electronic Fund Transfer "
        "Act (EFTA) and Fair Credit Billing Act (FCBA), consumers have limited liability "
        "for unauthorized credit card charges ($50 max or $0 if reported promptly). "
        "Issuers must provisionally credit disputed amounts during investigation."
    ),
    "account_closure": (
        "CFPB guidance: Creditors must provide adverse action notices (ECOA / Reg B) "
        "when closing accounts based on creditworthiness. Security deposits must be "
        "returned within a reasonable time following account closure."
    ),
    "credit_reporting": (
        "FCRA (15 U.S.C. § 1681): Credit reporting agencies must investigate disputed "
        "information within 30 days. Furnishers must correct or delete inaccurate data. "
        "Consumers may sue for willful or negligent noncompliance."
    ),
    "interest_fees": (
        "CARD Act of 2009 (15 U.S.C. § 1637): Prohibits retroactive rate increases on "
        "existing balances except under specific conditions. Requires 45-day advance "
        "notice for significant rate increases."
    ),
    "default": (
        "CFPB general standard: Companies must respond to consumer complaints in a "
        "timely and substantive manner. Consumers have the right to a fair and "
        "transparent resolution process under applicable federal consumer financial law."
    ),
}


def _pick_policy_excerpt(issue: str, tags: list[str]) -> str:
    """Select the most relevant policy excerpt based on issue text and tags."""
    issue_lower = (issue or "").lower()
    all_signals = issue_lower + " " + " ".join(tags)

    priority = [
        ("billing_dispute",  ["billing", "dispute", "statement", "charge"]),
        ("fraud",            ["fraud", "unauthorized", "stolen", "identity"]),
        ("account_closure",  ["clos", "terminat", "cancel"]),
        ("credit_reporting", ["credit report", "bureau", "score", "equifax"]),
        ("interest_fees",    ["interest", "apr", "rate", "fee"]),
    ]
    for key, signals in priority:
        if any(s in all_signals for s in signals):
            return _POLICY_EXCERPTS[key]
    return _POLICY_EXCERPTS["default"]


def _format_case(case: dict, idx: int) -> dict:
    """Format a single retrieved case for the context JSON."""
    best_segment = max(case["segments"], key=lambda s: s["similarity"]) if case["segments"] else {}
    snippet = best_segment.get("text_snippet", "")[:MAX_SNIPPET_CHARS]

    return {
        "rank":         idx + 1,
        "complaint_id": case["complaint_id"],
        "product":      case.get("product", ""),
        "issue":        case.get("issue", ""),
        "resolution":   case.get("resolution", ""),
        "disputed":     case.get("disputed", False),
        "similarity":   round(case.get("max_score", 0), 4),
        "snippet":      snippet,
    }


def build_context(
    complaint_text:         str,
    product:                str,
    issue:                  str,
    retrieval_result:       dict,
    historical_relief_rate: float = 0.5,
    extra_metadata:         Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Build the structured context dict that gets passed to every LLM agent.

    Parameters:
        complaint_text        : The consumer's narrative
        product               : e.g. "Credit card"
        issue                 : e.g. "Billing dispute"
        retrieval_result      : Output of retriever.retrieve_similar_cases()
        historical_relief_rate: Fraction of similar cases that got monetary relief
        extra_metadata        : Any additional fields (company, state, date, etc.)

    Returns structured context dict.
    """
    cases       = retrieval_result.get("cases", [])
    cold_start  = retrieval_result.get("cold_start", True)

    # Collect tags from all retrieved cases for policy selection
    all_tags: list[str] = []
    for c in cases:
        payload_tags = c.get("metadata_json", {}).get("tags", [])
        all_tags.extend(payload_tags)

    policy_excerpt = _pick_policy_excerpt(issue, all_tags)

    # Format retrieved cases (cap at MAX_CASES_IN_OUTPUT)
    formatted_cases = [
        _format_case(c, i)
        for i, c in enumerate(cases[:MAX_CASES_IN_OUTPUT])
    ]

    # Truncate complaint text to leave room for cases + policy
    truncated_text = complaint_text[:MAX_CONTEXT_CHARS]

    context = {
        "complaint_text":          truncated_text,
        "product":                 product,
        "issue":                   issue,
        "retrieved_cases":         formatted_cases,
        "total_similar_found":     retrieval_result.get("total_found", 0),
        "cold_start":              cold_start,
        "policy_excerpt":          policy_excerpt,
        "historical_relief_rate":  round(historical_relief_rate, 3),
    }

    if extra_metadata:
        context["metadata"] = extra_metadata

    if cold_start:
        context["cold_start_note"] = (
            "WARNING: Fewer than 5 similar cases found. "
            "Confidence scores will be penalised. "
            "Rely more heavily on policy excerpt and complaint text."
        )

    return context
