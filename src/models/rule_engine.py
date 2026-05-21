"""
Rule-based fraud signals.

The rule engine produces explainable signals that complement the ML model.
Each rule returns a (triggered: bool, weight: float, reason: str) tuple.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


HIGH_RISK_COUNTRIES = {"NG", "RU", "CN"}
HIGH_RISK_CATEGORIES = {"gambling", "crypto", "wire_transfer"}


@dataclass
class RuleHit:
    name: str
    weight: float
    reason: str


class RuleEngine:
    """Configurable rule engine that returns triggered rules + a risk score."""

    def __init__(self, high_amount_threshold: float = 2000.0) -> None:
        self.high_amount_threshold = high_amount_threshold

    def evaluate(self, txn: Dict[str, Any]) -> Tuple[float, List[RuleHit]]:
        hits: List[RuleHit] = []

        amount = float(txn.get("amount", 0.0))
        if amount >= self.high_amount_threshold:
            hits.append(RuleHit(
                name="high_amount",
                weight=0.30,
                reason=f"Amount ${amount:,.2f} exceeds ${self.high_amount_threshold:,.0f} threshold",
            ))

        if txn.get("country") in HIGH_RISK_COUNTRIES:
            hits.append(RuleHit(
                name="high_risk_country",
                weight=0.25,
                reason=f"Transaction from high-risk country: {txn.get('country')}",
            ))

        if txn.get("merchant_category") in HIGH_RISK_CATEGORIES:
            hits.append(RuleHit(
                name="high_risk_merchant",
                weight=0.20,
                reason=f"High-risk merchant category: {txn.get('merchant_category')}",
            ))

        hour = int(txn.get("hour", 12))
        if hour < 5 and amount > 300:
            hits.append(RuleHit(
                name="odd_hour",
                weight=0.15,
                reason=f"Unusual hour ({hour:02d}:00) with amount ${amount:,.2f}",
            ))

        if not txn.get("is_card_present", True) and amount > 1000:
            hits.append(RuleHit(
                name="card_not_present_high_value",
                weight=0.15,
                reason=f"Card-not-present transaction of ${amount:,.2f}",
            ))

        # cap rule score at 1.0
        score = min(sum(h.weight for h in hits), 1.0)
        return score, hits
