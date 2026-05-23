"""
Live transaction stream — simulates real merchant activity on the
user's cards so the dashboard feels like a live bank.

For each user with the stream enabled, a background thread fires a
new transaction every few seconds. The transactions go through the
exact same pipeline a real-world payment would: preflight checks,
the fraud model, the SSE event bus, and the database.

This is what gives the demo the "feels real" property: balances move,
the dashboard ticks, alerts pop, and the live feed is never empty.
"""

from __future__ import annotations

import logging
import random
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, Optional

from src.database import db
from src.database.models import BankAccount, Card, TransactionRecord


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# realistic merchant catalog — names + categories + typical amount range
# ---------------------------------------------------------------------
MERCHANTS = [
    # Daily small purchases (most common)
    ("Starbucks Coffee",      "restaurant",      4.95,    18.50, "US", True),
    ("Whole Foods Market",    "grocery",        15.00,   180.00, "US", True),
    ("Trader Joe's",          "grocery",        25.00,   120.00, "US", True),
    ("Subway",                "restaurant",      8.00,    24.00, "US", True),
    ("Chipotle",              "restaurant",     11.00,    32.00, "US", True),
    ("McDonald's",            "restaurant",      6.50,    22.00, "US", True),
    ("Shell Gas Station",     "fuel",           28.00,    85.00, "US", True),
    ("Chevron",               "fuel",           32.00,    78.00, "US", True),
    ("CVS Pharmacy",          "healthcare",     12.00,    65.00, "US", True),
    ("Walgreens",             "healthcare",      8.00,    55.00, "US", True),
    # Occasional larger
    ("Amazon",                "online_retail",  18.00,   240.00, "US", False),
    ("Target",                "online_retail",  20.00,   180.00, "US", True),
    ("Best Buy",              "electronics",   100.00,   850.00, "US", True),
    ("Apple Store",           "electronics",    99.00,  1299.00, "US", True),
    ("Netflix",               "entertainment",  15.49,    15.49, "US", False),
    ("Spotify",               "entertainment",   9.99,    11.99, "US", False),
    # Travel
    ("Uber",                  "travel",          7.00,    62.00, "US", False),
    ("Lyft",                  "travel",          8.00,    58.00, "US", False),
    ("Marriott Hotel",        "travel",        180.00,   620.00, "US", True),
    ("Delta Airlines",        "travel",        180.00,   850.00, "US", False),
    # Utilities
    ("PG&E",                  "utilities",      45.00,   220.00, "US", False),
    ("Verizon Wireless",      "utilities",      55.00,   180.00, "US", False),
]

# Suspicious / risky merchants — used to inject the occasional fraud attempt
SUSPICIOUS_MERCHANTS = [
    ("Anonymous Crypto Swap",        "crypto",        500.00,  4800.00, "RU", False),
    ("Offshore Wire Transfers Ltd",  "wire_transfer", 800.00,  9500.00, "NG", False),
    ("LuckyDice Casino",             "gambling",      200.00,  3000.00, "CN", False),
    ("BitMart Exchange",             "crypto",        150.00,  3500.00, "VE", False),
    ("Quick ATM Cashout",            "atm_withdrawal",400.00,   900.00, "BR", True),
    ("Premium Electronics RU",       "electronics",   600.00,  2400.00, "RU", False),
    ("Discount Luxury Watch CN",     "luxury",        450.00,  1900.00, "CN", False),
]

DEVICE_TYPES_NORMAL = ["mobile_ios", "mobile_android", "web_chrome", "web_safari", "pos_terminal"]
DEVICE_TYPES_RISKY  = ["web_firefox", "web_chrome"]


# ---------------------------------------------------------------------
# StreamManager — one background thread per user
# ---------------------------------------------------------------------
class StreamManager:
    """Per-process registry of running per-user streams.

    Threads are daemonized so they don't block process shutdown.
    Use ``start(user_id)`` and ``stop(user_id)`` to control. ``status``
    returns whether the stream is running plus how many transactions
    it has produced this session.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._workers: Dict[int, "_StreamWorker"] = {}

    def start(self, app, user_id: int, rate_per_min: int = 12,
              fraud_rate: float = 0.08) -> Dict[str, Any]:
        with self._lock:
            existing = self._workers.get(user_id)
            if existing and existing.is_alive():
                return {"running": True, "count": existing.count,
                        "rate_per_min": existing.rate_per_min,
                        "fraud_rate": existing.fraud_rate,
                        "started_at": existing.started_at.isoformat()}

            worker = _StreamWorker(app, user_id,
                                   rate_per_min=rate_per_min,
                                   fraud_rate=fraud_rate)
            worker.start()
            self._workers[user_id] = worker
            return {"running": True, "count": 0, "rate_per_min": rate_per_min,
                    "fraud_rate": fraud_rate,
                    "started_at": worker.started_at.isoformat()}

    def stop(self, user_id: int) -> Dict[str, Any]:
        with self._lock:
            worker = self._workers.pop(user_id, None)
        if worker:
            worker.stop()
            return {"running": False, "count": worker.count}
        return {"running": False, "count": 0}

    def status(self, user_id: int) -> Dict[str, Any]:
        with self._lock:
            worker = self._workers.get(user_id)
        if worker and worker.is_alive():
            return {"running": True, "count": worker.count,
                    "rate_per_min": worker.rate_per_min,
                    "fraud_rate": worker.fraud_rate,
                    "started_at": worker.started_at.isoformat()}
        return {"running": False, "count": 0}

    def stop_all(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for w in workers:
            w.stop()


class _StreamWorker(threading.Thread):
    """Background thread that fires transactions for one user."""

    def __init__(self, app, user_id: int, rate_per_min: int,
                 fraud_rate: float) -> None:
        super().__init__(daemon=True, name=f"livestream-user-{user_id}")
        self._app = app
        self.user_id = user_id
        self.rate_per_min = max(1, min(int(rate_per_min), 120))
        self.fraud_rate = max(0.0, min(float(fraud_rate), 0.5))
        self._stop_evt = threading.Event()
        self.count = 0
        self.started_at = datetime.utcnow()

    def stop(self) -> None:
        self._stop_evt.set()

    def run(self) -> None:
        # Average gap between transactions, jittered ±40%.
        base_gap = 60.0 / self.rate_per_min
        log.info("livestream user=%s rate=%d/min fraud=%.2f start",
                 self.user_id, self.rate_per_min, self.fraud_rate)

        while not self._stop_evt.is_set():
            jitter = random.uniform(0.6, 1.4)
            wait = base_gap * jitter
            if self._stop_evt.wait(timeout=wait):
                break

            try:
                self._fire_one_transaction()
                self.count += 1
            except Exception as exc:                       # pragma: no cover
                log.warning("livestream tick failed: %s", exc)
                # short cool-down so a persistent error doesn't tight-loop
                self._stop_evt.wait(timeout=5)

        log.info("livestream user=%s stop count=%d", self.user_id, self.count)

    # ------------------------------------------------------------------
    def _fire_one_transaction(self) -> None:
        """Pick a card, build a transaction, run fraud detection, persist."""
        with self._app.app_context():
            cards = (Card.query
                     .filter_by(user_id=self.user_id, status='active')
                     .all())
            usable = [c for c in cards if c.is_usable]
            if not usable:
                return

            card = random.choice(usable)
            account = card.account
            if account is None or account.status != 'active':
                return

            is_fraud_attempt = random.random() < self.fraud_rate
            txn_data = _build_synthetic_transaction(card, account, is_fraud_attempt)
            self._score_and_record(card, account, txn_data, is_fraud_attempt)

    def _score_and_record(self, card: Card, account: BankAccount,
                          data: Dict[str, Any], is_fraud_attempt: bool) -> None:
        """Run the fraud model and update card/account/balances."""
        model = self._app.config.get("FRAUD_MODEL")
        monitor = self._app.config.get("MONITOR")
        alert_mgr = self._app.config.get("ALERTS")
        event_bus = self._app.config.get("EVENT_BUS")

        if model is None or not model.is_trained:
            return

        # Refresh per-day counter
        card.reset_daily_spent_if_needed()

        amount = data["amount"]
        country = data["country"]
        is_card_present = data["is_card_present"]
        merchant_name = data["merchant_name"]
        category = data["merchant_category"]
        device = data["device_type"]
        hour = data["hour"]

        # ---- preflight (mirrors banking.routes.pay) -----------------
        precheck_reason = None
        if amount > account.available_balance:
            precheck_reason = "insufficient funds"
        elif amount > (card.daily_limit or 0) - (card.daily_spent or 0):
            precheck_reason = "daily limit exceeded"
        elif (country or '').upper() != (account.country or 'US').upper() \
                and not card.international_enabled:
            precheck_reason = "international transactions disabled"
        elif not is_card_present and not card.online_enabled:
            precheck_reason = "online transactions disabled"

        txn_id = f"live_{uuid.uuid4().hex[:14]}"
        if precheck_reason is not None:
            self._persist(
                txn_id=txn_id, card=card, account=account, data=data,
                decision="declined",
                fraud_probability=0.0, risk_level="low",
                model_score=0.0, rule_score=0.0,
                triggered_rules=[{"name": "preflight", "weight": 0.0,
                                  "reason": precheck_reason}],
                latency_ms=0.0,
            )
            self._publish(event_bus, card, account, txn_id, data,
                          decision="declined", fraud=None,
                          preflight_failure=True)
            return

        # ---- fraud scoring ------------------------------------------
        scoring_input = {
            "transaction_id": txn_id,
            "user_id": str(self.user_id),
            "amount": amount,
            "currency": account.currency,
            "country": country,
            "merchant_category": category,
            "merchant_name": merchant_name,
            "hour": hour,
            "device_type": device,
            "is_card_present": is_card_present,
            "card_last4": card.last4,
            "card_brand": card.brand,
        }
        start = time.perf_counter()
        prediction = model.predict(scoring_input)
        latency_ms = (time.perf_counter() - start) * 1000.0
        result_dict = asdict(prediction)
        decision = prediction.decision   # approve | review | decline

        # ---- act on decision ----------------------------------------
        if decision == "approve":
            account.balance -= amount
            account.available_balance -= amount
            card.daily_spent = (card.daily_spent or 0.0) + amount
            card.last_used_at = datetime.utcnow()
            new_status = "approved"
        elif decision == "review":
            account.available_balance -= amount
            card.last_used_at = datetime.utcnow()
            new_status = "held_for_review"
        else:
            new_status = "declined"
            if prediction.risk_level == "critical":
                card.status = "blocked"
                card.blocked_reason = (
                    f"Auto-blocked after critical fraud risk on transaction {txn_id}"
                )

        self._persist(
            txn_id=txn_id, card=card, account=account, data=data,
            decision=new_status,
            fraud_probability=prediction.fraud_probability,
            risk_level=prediction.risk_level,
            model_score=prediction.model_score,
            rule_score=prediction.rule_score,
            triggered_rules=result_dict.get("triggered_rules", []),
            latency_ms=latency_ms,
        )

        # ---- side effects -------------------------------------------
        if monitor is not None:
            monitor.record(scoring_input, result_dict, latency_ms)
        if prediction.risk_level in {"high", "critical"} and alert_mgr is not None:
            alert_mgr.raise_alert(
                transaction_id=txn_id,
                risk_level=prediction.risk_level,
                fraud_probability=prediction.fraud_probability,
                decision=new_status,
                reasons=[r["reason"] for r in result_dict.get("triggered_rules", [])],
            )

        self._publish(event_bus, card, account, txn_id, data,
                      decision=new_status,
                      fraud={"risk_level": prediction.risk_level,
                             "fraud_probability": prediction.fraud_probability,
                             "model_score": prediction.model_score,
                             "rule_score": prediction.rule_score})

    # ------------------------------------------------------------------
    def _persist(self, *, txn_id: str, card: Card, account: BankAccount,
                 data: Dict[str, Any], decision: str,
                 fraud_probability: float, risk_level: str,
                 model_score: float, rule_score: float,
                 triggered_rules: list, latency_ms: float) -> None:
        record = TransactionRecord(
            transaction_id=txn_id,
            amount=data["amount"],
            country=data["country"],
            merchant_category=data["merchant_category"],
            device_type=data["device_type"],
            hour=data["hour"],
            is_card_present=data["is_card_present"],
            is_fraud=risk_level in ("high", "critical"),
            fraud_probability=fraud_probability,
            risk_level=risk_level,
            decision=decision,
            model_score=model_score,
            rule_score=rule_score,
            triggered_rules=triggered_rules,
            latency_ms=latency_ms,
            processed_by="live_stream",
            user_id=self.user_id,
            bank_account_id=account.id,
            card_id=card.id,
            merchant_name=data["merchant_name"],
            currency=account.currency,
        )
        db.session.add(record)
        db.session.commit()

    def _publish(self, bus, card: Card, account: BankAccount,
                 txn_id: str, data: Dict[str, Any], *,
                 decision: str, fraud: Optional[Dict[str, Any]] = None,
                 preflight_failure: bool = False) -> None:
        if bus is None:
            return
        bus.publish("banking.payment", {
            "transaction": {
                "transaction_id": txn_id,
                "amount": data["amount"],
                "country": data["country"],
                "merchant_category": data["merchant_category"],
                "merchant_name": data["merchant_name"],
                "currency": account.currency,
                "decision": decision,
                "card_id": card.id,
                "bank_account_id": account.id,
                "user_id": self.user_id,
                "processed_at": datetime.utcnow().isoformat(),
                "risk_level": fraud.get("risk_level") if fraud else "low",
            },
            "card": card.to_dict(),
            "account": account.to_dict(),
            "user_id": self.user_id,
            "preflight_failure": preflight_failure,
            "live": True,
        })


# ---------------------------------------------------------------------
# Synthetic transaction builder
# ---------------------------------------------------------------------
def _build_synthetic_transaction(card: Card, account: BankAccount,
                                 is_fraud_attempt: bool) -> Dict[str, Any]:
    """Pick a merchant + amount + context tailored to the card.

    Real-feeling distribution:
      - 92% legit: routine merchants, account country, normal hours
      - 8%  fraud: suspicious merchants, foreign country, odd hours
    """
    if is_fraud_attempt:
        name, category, lo, hi, country, _card_present = random.choice(SUSPICIOUS_MERCHANTS)
        device = random.choice(DEVICE_TYPES_RISKY)
        is_card_present = False
        # fraud prefers off-hours
        hour = random.choice([0, 1, 2, 3, 4, 23])
        amount = round(random.uniform(lo, hi), 2)
    else:
        name, category, lo, hi, _country, card_present_typical = random.choice(MERCHANTS)
        device = random.choice(DEVICE_TYPES_NORMAL)
        is_card_present = card_present_typical and random.random() < 0.7
        # legit traffic peaks during waking hours
        hour = random.choices(
            list(range(24)),
            weights=[1, 1, 1, 1, 1, 2, 4, 7, 9, 9, 9, 10,
                     11, 10, 10, 10, 10, 9, 9, 8, 7, 5, 3, 2],
        )[0]
        amount = round(random.uniform(lo, hi), 2)
        # use the account's home country for legit traffic
        country = (account.country or "US").upper()

    return {
        "amount": amount,
        "country": country,
        "merchant_category": category,
        "merchant_name": name,
        "device_type": device,
        "is_card_present": is_card_present,
        "hour": hour,
    }


# Module-level singleton — created once per app.
_manager: Optional[StreamManager] = None


def get_manager() -> StreamManager:
    """Return the process-wide StreamManager, creating it on first call."""
    global _manager
    if _manager is None:
        _manager = StreamManager()
    return _manager
