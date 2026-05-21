"""
Real-time transaction monitor.

Maintains rolling statistics over recent transactions for the dashboard:
counts, fraud counts, average latency, top risky countries / categories.
"""

from __future__ import annotations

from collections import Counter, deque
from datetime import datetime
from threading import Lock
from typing import Any, Deque, Dict, List


class TransactionMonitor:
    """Thread-safe rolling window of recent transactions."""

    def __init__(self, window_size: int = 500) -> None:
        self._txns: Deque[Dict[str, Any]] = deque(maxlen=window_size)
        self._lock = Lock()
        self._latencies: Deque[float] = deque(maxlen=window_size)
        self._created_at = datetime.utcnow()

    # ------------------------------------------------------------------
    # ingestion
    # ------------------------------------------------------------------
    def record(self, transaction: Dict[str, Any], result: Dict[str, Any], latency_ms: float) -> Dict[str, Any]:
        record = {
            "transaction": transaction,
            "result": result,
            "latency_ms": round(latency_ms, 2),
            "recorded_at": datetime.utcnow().isoformat(),
        }
        with self._lock:
            self._txns.appendleft(record)
            self._latencies.append(latency_ms)
        return record

    # ------------------------------------------------------------------
    # views
    # ------------------------------------------------------------------
    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._txns)[:limit]

    def metrics(self) -> Dict[str, Any]:
        with self._lock:
            txns = list(self._txns)
            latencies = list(self._latencies)

        total = len(txns)
        fraud = sum(1 for t in txns if t["result"].get("is_fraud"))
        declined = sum(1 for t in txns if t["result"].get("decision") == "decline")
        review = sum(1 for t in txns if t["result"].get("decision") == "review")
        approved = total - declined - review

        risk_counts = Counter(t["result"].get("risk_level", "low") for t in txns)
        country_fraud = Counter(
            t["transaction"].get("country", "??")
            for t in txns
            if t["result"].get("is_fraud")
        )
        category_fraud = Counter(
            t["transaction"].get("merchant_category", "unknown")
            for t in txns
            if t["result"].get("is_fraud")
        )

        # 24-bucket hourly volume / fraud over the window
        hourly = [{"hour": h, "total": 0, "fraud": 0} for h in range(24)]
        for t in txns:
            h = int(t["transaction"].get("hour", 0)) % 24
            hourly[h]["total"] += 1
            if t["result"].get("is_fraud"):
                hourly[h]["fraud"] += 1

        avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0

        return {
            "total_transactions": total,
            "fraud_detected": fraud,
            "fraud_rate": round(fraud / total, 4) if total else 0.0,
            "approved": approved,
            "review": review,
            "declined": declined,
            "avg_latency_ms": avg_latency,
            "risk_distribution": {
                "low": risk_counts.get("low", 0),
                "medium": risk_counts.get("medium", 0),
                "high": risk_counts.get("high", 0),
                "critical": risk_counts.get("critical", 0),
            },
            "top_fraud_countries": country_fraud.most_common(5),
            "top_fraud_categories": category_fraud.most_common(5),
            "hourly": hourly,
            "uptime_seconds": int((datetime.utcnow() - self._created_at).total_seconds()),
        }
