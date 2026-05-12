"""
Regulatory Compliance Agent (weight: 30%)

Evaluates complaint against CFPB regulations:
FCRA, ECOA, CARD Act, Regulation Z, EFTA/FCBA.
"""

from agents.base_agent import BaseAgent


class ComplianceAgent(BaseAgent):
    name   = "regulatory_compliance"
    weight = 0.30

    @property
    def system_prompt(self) -> str:
        return (
            "You are a Senior Regulatory Compliance Analyst specializing in US consumer "
            "financial law. You have deep expertise in:\n"
            "- CFPB regulations and enforcement priorities\n"
            "- Fair Credit Reporting Act (FCRA)\n"
            "- Equal Credit Opportunity Act (ECOA) / Regulation B\n"
            "- CARD Act (15 U.S.C. § 1637)\n"
            "- Regulation Z (Truth in Lending / billing disputes)\n"
            "- Electronic Fund Transfer Act (EFTA) / Fair Credit Billing Act (FCBA)\n\n"
            "You identify specific regulatory violations with citation precision. "
            "You respond ONLY with valid JSON."
        )

    @property
    def focus_description(self) -> str:
        return (
            "Identify specific regulatory violations (FCRA, ECOA, CARD Act, Reg Z, FCBA). "
            "Cite which statute/regulation was breached and by what action."
        )
