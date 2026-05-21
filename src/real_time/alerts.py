"""
Alert management.

Stores alerts in memory and exposes hooks for email / SMS / webhook
delivery. In a production deployment, replace `_dispatch` with calls
to your preferred providers (Twilio, SendGrid, Slack, etc.).
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from threading import Lock
from typing import Any, Deque, Dict, List, Optional


logger = logging.getLogger(__name__)


class AlertManager:
    """Thread-safe alert store with an in-memory ring buffer."""

    def __init__(self, max_alerts: int = 200) -> None:
        self._alerts: Deque[Dict[str, Any]] = deque(maxlen=max_alerts)
        self._lock = Lock()

    def raise_alert(
        self,
        transaction_id: str,
        risk_level: str,
        fraud_probability: float,
        decision: str,
        reasons: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        alert = {
            "id": f"alt_{int(datetime.utcnow().timestamp() * 1000)}",
            "transaction_id": transaction_id,
            "risk_level": risk_level,
            "fraud_probability": fraud_probability,
            "decision": decision,
            "reasons": reasons or [],
            "created_at": datetime.utcnow().isoformat(),
            "status": "open",
        }
        with self._lock:
            self._alerts.appendleft(alert)
        self._dispatch(alert)
        return alert

    def list_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._alerts)[:limit]

    def stats(self) -> Dict[str, int]:
        with self._lock:
            counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
            for a in self._alerts:
                lvl = a.get("risk_level", "low")
                counts[lvl] = counts.get(lvl, 0) + 1
            return counts

    # ------------------------------------------------------------------
    # delivery hooks (replace for production)
    # ------------------------------------------------------------------
    def _dispatch(self, alert: Dict[str, Any]) -> None:
        logger.info(
            "ALERT %s | %s | prob=%.2f | decision=%s",
            alert["risk_level"].upper(),
            alert["transaction_id"],
            alert["fraud_probability"],
            alert["decision"],
        )
