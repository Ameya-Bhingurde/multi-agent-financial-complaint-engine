"""
Base Agent — Multi-Agent Financial Complaint Governance Engine

Abstract class all five governance agents inherit from.
Handles:
  - LLM provider routing (Groq / OpenAI via LLM_PROVIDER env var)
  - Structured JSON output enforcement
  - Retry with exponential backoff on rate limits
  - Common prompt templating
"""

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

LLM_PROVIDER  = os.getenv("LLM_PROVIDER", "groq").lower()
GROQ_API_KEY  = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL    = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL  = os.getenv("OPENAI_MODEL", "gpt-4o")

MAX_RETRIES   = 1
INITIAL_DELAY = 2.0   # seconds


class BaseAgent(ABC):
    """Abstract base class for all governance agents."""

    name: str = "base"
    weight: float = 0.0

    # --- Abstract interface ---------------------------------------------------

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """The fixed system-level instructions for this agent's role."""
        ...

    @property
    @abstractmethod
    def focus_description(self) -> str:
        """One-line description of what this agent evaluates."""
        ...

    # --- LLM call layer -------------------------------------------------------

    def _call_llm(self, user_message: str) -> str:
        """Route to Groq or OpenAI, with retries."""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if LLM_PROVIDER == "openai":
                    return self._call_openai(user_message)
                return self._call_groq(user_message)
            except Exception as e:
                wait = INITIAL_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    f"[{self.name}] LLM call failed (attempt {attempt}/{MAX_RETRIES}): "
                    f"{e}. Retrying in {wait}s..."
                )
                if attempt == MAX_RETRIES:
                    raise
                time.sleep(wait)

    def _call_groq(self, user_message: str) -> str:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model    = GROQ_MODEL,
            messages = [
                {"role": "system",  "content": self.system_prompt},
                {"role": "user",    "content": user_message},
            ],
            temperature       = 0.1,
            max_tokens        = 800,
            response_format   = {"type": "json_object"},
        )
        return response.choices[0].message.content

    def _call_openai(self, user_message: str) -> str:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model    = OPENAI_MODEL,
            messages = [
                {"role": "system",  "content": self.system_prompt},
                {"role": "user",    "content": user_message},
            ],
            temperature     = 0.1,
            max_tokens      = 800,
            response_format = {"type": "json_object"},
        )
        return response.choices[0].message.content

    # --- Prompt building -------------------------------------------------------

    def _build_user_prompt(self, context: dict, round_num: int = 1,
                           peer_votes: list[dict] | None = None) -> str:
        prompt = f"""You are evaluating a consumer credit card complaint.

=== COMPLAINT ===
Product : {context.get('product', 'Credit card')}
Issue   : {context.get('issue', 'Unknown')}

Narrative:
{context.get('complaint_text', '')[:3000]}

=== SIMILAR PAST CASES ({context.get('total_similar_found', 0)} found) ===
"""
        for case in context.get("retrieved_cases", [])[:3]:
            prompt += (
                f"  #{case['rank']} | similarity={case['similarity']} | "
                f"resolution={case['resolution']} | disputed={case['disputed']}\n"
                f"  Snippet: {case['snippet'][:200]}\n\n"
            )

        prompt += f"""=== POLICY REFERENCE ===
{context.get('policy_excerpt', '')}

=== HISTORICAL RELIEF RATE ===
{context.get('historical_relief_rate', 0.5):.1%} of similar complaints received monetary relief.
"""
        if context.get("cold_start"):
            prompt += f"\n⚠️  {context.get('cold_start_note', 'Cold start — confidence penalty applied.')}\n"

        if round_num == 2 and peer_votes:
            prompt += "\n=== PEER AGENT SCORES (Round 1) — Consider before re-scoring ===\n"
            for v in peer_votes:
                prompt += (
                    f"  {v['agent_name']}: score={v['score']}, "
                    f"confidence={v['confidence']}\n"
                    f"  Reasoning: {v['reasoning'][:200]}\n\n"
                )

        prompt += f"""
=== YOUR TASK ===
Evaluate this complaint from your specific perspective: {self.focus_description}

Respond ONLY with valid JSON in this exact schema:
{{
  "score":       <float 0.0–10.0>,
  "confidence":  <float 0.0–1.0>,
  "risk_flags":  [<string>, ...],
  "reasoning":   "<2-3 sentence explanation>"
}}

Rules:
- score 0 = no issue found, 10 = severe violation requiring immediate relief
- confidence reflects how certain you are given the evidence available
- risk_flags: list specific violations or concerns (empty list [] if none)
"""
        return prompt

    # --- Public evaluate interface --------------------------------------------

    def evaluate(
        self,
        context: dict[str, Any],
        round_num: int = 1,
        peer_votes: list[dict] | None = None,
    ) -> dict[str, Any]:
        """
        Run this agent's evaluation. Returns a structured vote dict.
        """
        user_prompt = self._build_user_prompt(context, round_num, peer_votes)

        raw = self._call_llm(user_prompt)

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.error(f"[{self.name}] Failed to parse LLM JSON: {raw[:300]}")
            parsed = {
                "score":      5.0,
                "confidence": 0.1,
                "risk_flags": ["json_parse_error"],
                "reasoning":  "Agent returned malformed JSON. Using fallback score.",
            }

        # Clamp values to valid ranges
        parsed["score"]      = max(0.0, min(10.0, float(parsed.get("score", 5.0))))
        parsed["confidence"] = max(0.0, min(1.0,  float(parsed.get("confidence", 0.5))))
        parsed["risk_flags"] = parsed.get("risk_flags", [])
        parsed["reasoning"]  = str(parsed.get("reasoning", ""))
        parsed["agent_name"] = self.name
        parsed["round_num"]  = round_num
        parsed["raw_response"] = {"text": raw}

        logger.info(
            f"[{self.name}] Round {round_num} → "
            f"score={parsed['score']:.1f}, confidence={parsed['confidence']:.2f}"
        )
        return parsed
