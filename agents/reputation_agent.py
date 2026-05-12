"""
Reputation Risk Agent (weight: 10%)

Evaluates media exposure risk, escalation potential,
and reputational damage if the complaint goes unresolved.
"""

from agents.base_agent import BaseAgent


class ReputationAgent(BaseAgent):
    name   = "reputation_risk"
    weight = 0.10

    @property
    def system_prompt(self) -> str:
        return (
            "You are a Reputational Risk and Public Relations Analyst for a financial "
            "institution. You evaluate consumer complaints for:\n"
            "- Media / social media escalation potential\n"
            "- Patterns that could attract class-action litigation\n"
            "- Severity of consumer distress suggesting viral complaint potential\n"
            "- Public CFPB visibility (repeated systemic issues)\n"
            "- Regulatory inquiry risk if the complaint is unresolved\n\n"
            "Score purely from a PR / reputational lens — not legal compliance. "
            "High score = high reputational risk if unresolved. "
            "You respond ONLY with valid JSON."
        )

    @property
    def focus_description(self) -> str:
        return (
            "Assess reputational and escalation risk: media exposure potential, "
            "class-action indicators, CFPB visibility, consumer distress level."
        )
