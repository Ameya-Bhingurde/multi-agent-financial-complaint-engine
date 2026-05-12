"""
Fairness Agent (weight: 20%)

Evaluates for disparate impact, protected class signals,
and equitable treatment indicators.
"""

from agents.base_agent import BaseAgent


class FairnessAgent(BaseAgent):
    name   = "fairness"
    weight = 0.20

    @property
    def system_prompt(self) -> str:
        return (
            "You are a Consumer Fairness and Equity Analyst. You evaluate financial "
            "complaints for signs of:\n"
            "- Disparate impact on protected classes (race, gender, age, national origin)\n"
            "- Language suggesting discriminatory treatment\n"
            "- Inconsistent policies applied to different customer segments\n"
            "- Violations of ECOA / Reg B equal treatment standards\n"
            "- Predatory or deceptive practices that disproportionately harm vulnerable consumers\n\n"
            "You are careful not to over-attribute discrimination without evidence, "
            "but you flag any credible signals for escalation. "
            "You respond ONLY with valid JSON."
        )

    @property
    def focus_description(self) -> str:
        return (
            "Identify any disparate impact signals, protected class language, or "
            "indicators of inequitable treatment compared to similar consumer situations."
        )
