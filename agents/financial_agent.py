"""
Financial Impact Agent (weight: 20%)

Evaluates monetary harm: billing errors, fee overcharges,
withheld deposits, quantifiable financial loss.
"""

from agents.base_agent import BaseAgent


class FinancialAgent(BaseAgent):
    name   = "financial_impact"
    weight = 0.20

    @property
    def system_prompt(self) -> str:
        return (
            "You are a Financial Harm Assessment Specialist. You evaluate consumer "
            "complaints to determine the severity and verifiability of financial harm:\n"
            "- Specific dollar amounts disputed or lost\n"
            "- Erroneous fees, charges, or interest applied\n"
            "- Withheld deposits or funds not returned\n"
            "- Credit limit changes causing downstream financial harm\n"
            "- Lost rewards, benefits, or promotional terms\n\n"
            "Higher scores reflect larger or more clearly documented financial harm. "
            "Consider whether the consumer provided enough evidence to substantiate the claim. "
            "You respond ONLY with valid JSON."
        )

    @property
    def focus_description(self) -> str:
        return (
            "Quantify the financial harm: identify specific dollar amounts, erroneous fees, "
            "withheld funds, or billing errors. Rate severity based on documented evidence."
        )
