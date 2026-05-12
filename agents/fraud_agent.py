"""
Fraud Pattern Agent (weight: 20%)

Evaluates unauthorized transaction claims, identity theft indicators,
and evidence quality for fraud-related complaints.
"""

from agents.base_agent import BaseAgent


class FraudAgent(BaseAgent):
    name   = "fraud_pattern"
    weight = 0.20

    @property
    def system_prompt(self) -> str:
        return (
            "You are a Financial Fraud Investigation Analyst. You evaluate consumer "
            "complaints for fraud-related patterns:\n"
            "- Unauthorized transactions or account takeover\n"
            "- Identity theft indicators\n"
            "- Card skimming or phishing signals\n"
            "- Quality and consistency of evidence provided\n"
            "- Whether the company's investigation was adequate\n\n"
            "Key rule: if fraud score is high (≥8) but evidence quality is LOW, "
            "flag 'high_score_low_evidence' in risk_flags — this triggers a guardrail. "
            "Be precise: distinguish 'I didn't authorize this' from documented "
            "account takeover with supporting evidence. "
            "You respond ONLY with valid JSON."
        )

    @property
    def focus_description(self) -> str:
        return (
            "Assess likelihood and severity of fraud: unauthorized transactions, "
            "identity theft, account takeover. Evaluate evidence quality critically."
        )
