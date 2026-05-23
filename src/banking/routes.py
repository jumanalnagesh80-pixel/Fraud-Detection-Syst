"""
Banking REST endpoints.

Routes (all require an authenticated session unless noted):

  GET    /api/banking/overview            summary of accounts + cards + recent
  GET    /api/banking/accounts            list current user's accounts
  POST   /api/banking/accounts            open a new account
  GET    /api/banking/accounts/<id>       account detail + recent transactions
  POST   /api/banking/accounts/<id>/freeze   freeze / activate
  POST   /api/banking/accounts/<id>/unfreeze
  GET    /api/banking/cards               list current user's cards
  POST   /api/banking/cards               issue a new card
  GET    /api/banking/cards/<id>          card detail
  POST   /api/banking/cards/<id>/freeze   freeze
  POST   /api/banking/cards/<id>/unfreeze unfreeze (only if not blocked-by-fraud)
  POST   /api/banking/cards/<id>/limit    update daily limit
  POST   /api/banking/pay                 charge a card — runs fraud detection
                                          in real time and updates balances
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from src.database import db
from src.database.models import BankAccount, Card, TransactionRecord, User

from . import utils
from .live_stream import get_manager as _get_live_manager
from .seed import (
    DEFAULT_DAILY_CARD_LIMIT,
    DEFAULT_OPENING_BALANCE,
    seed_user_banking,
)

# Import here to avoid a circular import (extras_routes -> banking).
try:
    from src.api.extras_routes import push_notification
except Exception:                                     # pragma: no cover
    def push_notification(*_args, **_kwargs) -> None:  # type: ignore[misc]
        """Fallback no-op if notifications aren't wired up yet."""

log = logging.getLogger(__name__)


def create_banking_blueprint() -> Blueprint:
    bp = Blueprint("banking", __name__, url_prefix="/api/banking")

    # ==================================================================
    # OVERVIEW
    # ==================================================================
    @bp.get("/overview")
    @login_required
    def overview():
        """One-call dashboard summary for the banking page."""
        # Auto-seed lazily so the first visit always has data.
        seed_user_banking(current_user)
        db.session.commit()

        accounts = current_user.bank_accounts.all()
        cards = current_user.cards.all()
        recent = (TransactionRecord.query
                  .filter_by(user_id=current_user.id)
                  .order_by(TransactionRecord.processed_at.desc())
                  .limit(20)
                  .all())

        total_balance = sum(a.balance for a in accounts if a.status == 'active')
        active_cards = sum(1 for c in cards if c.is_usable)

        return jsonify({
            "summary": {
                "total_balance": round(total_balance, 2),
                "currency": (accounts[0].currency if accounts else 'USD'),
                "account_count": len(accounts),
                "active_cards": active_cards,
                "total_cards": len(cards),
            },
            "accounts": [a.to_dict() for a in accounts],
            "cards": [c.to_dict() for c in cards],
            "recent_transactions": [t.to_dict() for t in recent],
        })

    # ==================================================================
    # ACCOUNTS
    # ==================================================================
    @bp.get("/accounts")
    @login_required
    def list_accounts():
        accounts = current_user.bank_accounts.order_by(BankAccount.opened_at.asc()).all()
        return jsonify({
            "count": len(accounts),
            "accounts": [a.to_dict() for a in accounts],
        })

    @bp.post("/accounts")
    @login_required
    def create_account():
        data = request.get_json(silent=True) or {}
        account_type = (data.get("account_type") or "checking").lower()
        if account_type not in ("checking", "savings"):
            return jsonify({"error": "account_type must be 'checking' or 'savings'"}), 400

        currency = (data.get("currency") or current_user.preferred_currency or "USD").upper()
        country = (data.get("country") or current_user.country or "US").upper()
        nickname = (data.get("nickname") or
                    f"{account_type.title()} {current_user.bank_accounts.count() + 1}")
        # Optional opening deposit, capped to a sensible demo limit.
        opening = float(data.get("opening_deposit") or DEFAULT_OPENING_BALANCE)
        opening = max(0.0, min(opening, 100_000.0))

        account_number = _unique_account_number()
        account = BankAccount(
            user_id=current_user.id,
            account_number=account_number,
            iban=utils.generate_iban(country, account_number),
            routing_number=utils.generate_routing_number(),
            nickname=nickname[:80],
            account_type=account_type,
            currency=currency,
            country=country,
            balance=opening,
            available_balance=opening,
            status='active',
            is_primary=current_user.bank_accounts.count() == 0,
        )
        db.session.add(account)
        db.session.commit()

        _publish("banking.account_opened", {
            "account": account.to_dict(),
            "user_id": current_user.id,
        })
        return jsonify({"success": True, "account": account.to_dict()}), 201

    @bp.get("/accounts/<int:account_id>")
    @login_required
    def get_account(account_id: int):
        account = _get_owned_account(account_id)
        if account is None:
            return jsonify({"error": "account not found"}), 404
        recent = (TransactionRecord.query
                  .filter_by(bank_account_id=account.id)
                  .order_by(TransactionRecord.processed_at.desc())
                  .limit(50).all())
        return jsonify({
            "account": account.to_dict(),
            "cards": [c.to_dict() for c in account.cards.all()],
            "recent_transactions": [t.to_dict() for t in recent],
        })

    @bp.post("/accounts/<int:account_id>/freeze")
    @login_required
    def freeze_account(account_id: int):
        return _set_account_status(account_id, 'frozen')

    @bp.post("/accounts/<int:account_id>/unfreeze")
    @login_required
    def unfreeze_account(account_id: int):
        return _set_account_status(account_id, 'active')

    # ==================================================================
    # CARDS
    # ==================================================================
    @bp.get("/cards")
    @login_required
    def list_cards():
        cards = current_user.cards.order_by(Card.issued_at.desc()).all()
        # auto-reset daily-spent counters at UTC midnight
        for c in cards:
            c.reset_daily_spent_if_needed()
        db.session.commit()
        return jsonify({"count": len(cards), "cards": [c.to_dict() for c in cards]})

    @bp.post("/cards")
    @login_required
    def issue_card():
        data = request.get_json(silent=True) or {}
        account_id = data.get("account_id")
        account = _get_owned_account(account_id) if account_id else current_user.bank_accounts.first()
        if account is None:
            return jsonify({"error": "no account available — open one first"}), 400
        if account.status != 'active':
            return jsonify({"error": "account is not active"}), 400

        brand = (data.get("brand") or "visa").lower()
        card_type = (data.get("card_type") or "debit").lower()
        if card_type not in ("debit", "credit", "prepaid"):
            return jsonify({"error": "card_type must be debit/credit/prepaid"}), 400

        pan = utils.generate_card_number(brand)
        month, year = utils.generate_expiry()
        cvv = utils.generate_cvv(brand)
        cardholder = (data.get("cardholder_name") or current_user.full_name
                      or current_user.username or "Cardholder")

        card = Card(
            user_id=current_user.id,
            account_id=account.id,
            card_number_masked=utils.mask_pan(pan),
            last4=utils.last4(pan),
            pan_hash=utils.hash_pan(pan),
            cvv_hash=utils.hash_cvv(cvv),
            expiry_month=month,
            expiry_year=year,
            card_type=card_type,
            brand=brand,
            cardholder_name=cardholder.upper()[:120],
            nickname=(data.get("nickname") or f"{brand.title()} {card_type.title()}")[:80],
            daily_limit=float(data.get("daily_limit") or DEFAULT_DAILY_CARD_LIMIT),
            international_enabled=bool(data.get("international_enabled", False)),
            contactless_enabled=bool(data.get("contactless_enabled", True)),
            online_enabled=bool(data.get("online_enabled", True)),
            status='active',
        )
        db.session.add(card)
        db.session.commit()

        _publish("banking.card_issued", {"card": card.to_dict(), "user_id": current_user.id})

        # Return the full PAN + CVV ONCE so the user can copy them. After this
        # response they can never be retrieved again — only the masked form
        # and ``last4`` remain in the database.
        body = card.to_dict()
        body["card_number"] = pan
        body["cvv"] = cvv
        body["_warning"] = "Save these now — the full number and CVV are shown only once."
        return jsonify({"success": True, "card": body}), 201

    @bp.get("/cards/<int:card_id>")
    @login_required
    def get_card(card_id: int):
        card = _get_owned_card(card_id)
        if card is None:
            return jsonify({"error": "card not found"}), 404
        card.reset_daily_spent_if_needed()
        db.session.commit()
        recent = (TransactionRecord.query
                  .filter_by(card_id=card.id)
                  .order_by(TransactionRecord.processed_at.desc())
                  .limit(50).all())
        return jsonify({
            "card": card.to_dict(),
            "recent_transactions": [t.to_dict() for t in recent],
        })

    @bp.post("/cards/<int:card_id>/freeze")
    @login_required
    def freeze_card(card_id: int):
        return _set_card_status(card_id, 'frozen', reason='Frozen by user')

    @bp.post("/cards/<int:card_id>/unfreeze")
    @login_required
    def unfreeze_card(card_id: int):
        card = _get_owned_card(card_id)
        if card is None:
            return jsonify({"error": "card not found"}), 404
        if card.status == 'blocked':
            return jsonify({
                "error": "card was blocked due to fraud — contact support"
            }), 403
        return _set_card_status(card_id, 'active', reason=None)

    @bp.post("/cards/<int:card_id>/limit")
    @login_required
    def update_card_limit(card_id: int):
        card = _get_owned_card(card_id)
        if card is None:
            return jsonify({"error": "card not found"}), 404
        data = request.get_json(silent=True) or {}
        try:
            new_limit = float(data.get("daily_limit"))
        except (TypeError, ValueError):
            return jsonify({"error": "daily_limit must be a number"}), 400
        if new_limit < 0 or new_limit > 100_000:
            return jsonify({"error": "daily_limit must be between 0 and 100000"}), 400
        card.daily_limit = new_limit
        db.session.commit()
        return jsonify({"success": True, "card": card.to_dict()})

    @bp.post("/cards/<int:card_id>/toggle")
    @login_required
    def toggle_card_setting(card_id: int):
        """Toggle one of: international, contactless, online (boolean flags)."""
        card = _get_owned_card(card_id)
        if card is None:
            return jsonify({"error": "card not found"}), 404
        data = request.get_json(silent=True) or {}
        setting = data.get("setting")
        value = bool(data.get("enabled"))
        mapping = {
            "international": "international_enabled",
            "contactless": "contactless_enabled",
            "online": "online_enabled",
        }
        if setting not in mapping:
            return jsonify({"error": "setting must be international/contactless/online"}), 400
        setattr(card, mapping[setting], value)
        db.session.commit()
        return jsonify({"success": True, "card": card.to_dict()})

    # ==================================================================
    # PAYMENTS - the real-time fraud detection happens here
    # ==================================================================
    @bp.post("/pay")
    @login_required
    def pay():
        """Charge a card. Runs fraud detection in real-time.

        Request body:
        {
            "card_id": 1,
            "amount": 49.95,
            "merchant_name": "Acme Coffee",
            "merchant_category": "restaurant",
            "country": "US",
            "device_type": "pos_terminal",   # optional
            "is_card_present": true          # optional
        }
        """
        data = request.get_json(silent=True) or {}
        card = _get_owned_card(data.get("card_id"))
        if card is None:
            return jsonify({"error": "card not found"}), 404

        # ---------- structural validation ---------------------------------
        try:
            amount = float(data.get("amount") or 0)
        except (TypeError, ValueError):
            return jsonify({"error": "amount must be a number"}), 400
        if amount <= 0:
            return jsonify({"error": "amount must be positive"}), 400
        if amount > 1_000_000:
            return jsonify({"error": "amount exceeds maximum per-transaction limit"}), 400

        country = (data.get("country") or card.account.country or "US").upper()[:10]
        category = (data.get("merchant_category") or "online_retail")[:50]
        merchant_name = (data.get("merchant_name") or "Unknown Merchant")[:120]
        device = (data.get("device_type") or "web_chrome")[:50]
        is_card_present = bool(data.get("is_card_present", False))
        hour = datetime.utcnow().hour

        # ---------- pre-flight card / account checks ----------------------
        card.reset_daily_spent_if_needed()
        account = card.account
        precheck = _precheck_payment(card, account, amount, country, is_card_present)
        if precheck is not None:
            decision, reason = precheck
            return _record_declined(
                card, account, amount, country, category, merchant_name,
                device, hour, is_card_present, decision=decision, reason=reason,
            )

        # ---------- fraud detection (ML + rules) --------------------------
        model = current_app.config["FRAUD_MODEL"]
        monitor = current_app.config["MONITOR"]
        alert_mgr = current_app.config["ALERTS"]

        txn_id = f"pay_{uuid.uuid4().hex[:16]}"
        txn_dict = {
            "transaction_id": txn_id,
            "user_id": str(current_user.id),
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
        prediction = model.predict(txn_dict)
        latency_ms = (time.perf_counter() - start) * 1000.0
        result_dict = asdict(prediction)
        decision = prediction.decision  # approve | review | decline

        # ---------- act on the decision -----------------------------------
        card_blocked = False
        if decision == 'approve':
            account.balance -= amount
            account.available_balance -= amount
            card.daily_spent = (card.daily_spent or 0.0) + amount
            card.last_used_at = datetime.utcnow()
            new_status = 'approved'
        elif decision == 'review':
            # hold the funds: drops available_balance but balance is still
            # subject to release after manual review
            account.available_balance -= amount
            card.last_used_at = datetime.utcnow()
            new_status = 'held_for_review'
        else:                                        # decline
            new_status = 'declined'
            if prediction.risk_level == 'critical':
                card.status = 'blocked'
                card.blocked_reason = (
                    f"Auto-blocked after critical fraud risk on transaction {txn_id}"
                )
                card_blocked = True

        # ---------- persist transaction record ----------------------------
        record = TransactionRecord(
            transaction_id=txn_id,
            amount=amount,
            country=country,
            merchant_category=category,
            device_type=device,
            hour=hour,
            is_card_present=is_card_present,
            is_fraud=prediction.is_fraud,
            fraud_probability=prediction.fraud_probability,
            risk_level=prediction.risk_level,
            decision=new_status,
            model_score=prediction.model_score,
            rule_score=prediction.rule_score,
            triggered_rules=result_dict.get("triggered_rules", []),
            latency_ms=latency_ms,
            processed_by=current_user.username,
            user_id=current_user.id,
            bank_account_id=account.id,
            card_id=card.id,
            merchant_name=merchant_name,
            currency=account.currency,
        )
        db.session.add(record)
        db.session.commit()

        # ---------- side effects: monitor, alerts, notifications, SSE -----
        monitor_record = monitor.record(txn_dict, result_dict, latency_ms)
        if prediction.risk_level in {"high", "critical"}:
            alert_mgr.raise_alert(
                transaction_id=txn_id,
                risk_level=prediction.risk_level,
                fraud_probability=prediction.fraud_probability,
                decision=new_status,
                reasons=[r["reason"] for r in result_dict.get("triggered_rules", [])],
            )
            push_notification(
                current_app, current_user.id,
                type_='fraud_alert',
                title=f"Suspicious payment {new_status}",
                message=(f"${amount:,.2f} at {merchant_name} ({country}) flagged "
                         f"as {prediction.risk_level}."),
                level=prediction.risk_level,
            )

        _publish("banking.payment", {
            "transaction": record.to_dict(),
            "monitor_entry": monitor_record,
            "card": card.to_dict(),
            "account": account.to_dict(),
            "user_id": current_user.id,
        })
        if card_blocked:
            _publish("card.blocked", {
                "card_id": card.id, "last4": card.last4,
                "reason": card.blocked_reason, "user_id": current_user.id,
            })
            push_notification(
                current_app, current_user.id,
                type_='card_blocked',
                title=f"Card **** {card.last4} blocked",
                message="A critical fraud risk was detected. The card has been blocked for your safety.",
                level='critical',
            )

        return jsonify({
            "success": decision == 'approve',
            "decision": new_status,
            "transaction": record.to_dict(),
            "fraud": {
                "risk_level": prediction.risk_level,
                "fraud_probability": prediction.fraud_probability,
                "model_score": prediction.model_score,
                "rule_score": prediction.rule_score,
                "triggered_rules": result_dict.get("triggered_rules", []),
                "latency_ms": round(latency_ms, 2),
            },
            "card": card.to_dict(),
            "account": account.to_dict(),
        }), 200 if decision == 'approve' else 402

    # ==================================================================
    # LIVE STREAM - simulated real merchant activity on the user's cards
    # ==================================================================
    @bp.get("/stream/status")
    @login_required
    def stream_status():
        return jsonify(_get_live_manager().status(current_user.id))

    @bp.post("/stream/start")
    @login_required
    def stream_start():
        data = request.get_json(silent=True) or {}
        try:
            rate = int(data.get("rate_per_min", 12))
        except (TypeError, ValueError):
            rate = 12
        try:
            fraud_rate = float(data.get("fraud_rate", 0.08))
        except (TypeError, ValueError):
            fraud_rate = 0.08

        # Make sure the user actually has a card to charge
        if not current_user.cards.filter_by(status='active').first():
            return jsonify({
                "error": "no active card available — issue one first",
            }), 400

        result = _get_live_manager().start(
            current_app._get_current_object(),
            user_id=current_user.id,
            rate_per_min=rate,
            fraud_rate=fraud_rate,
        )
        _publish("banking.live_stream", {
            "user_id": current_user.id, "running": True, **result,
        })
        return jsonify({"success": True, **result})

    @bp.post("/stream/stop")
    @login_required
    def stream_stop():
        result = _get_live_manager().stop(current_user.id)
        _publish("banking.live_stream", {
            "user_id": current_user.id, "running": False, **result,
        })
        return jsonify({"success": True, **result})

    return bp


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _publish(event_type: str, payload: Dict[str, Any]) -> None:
    """Publish to the SSE bus, swallowing any errors."""
    try:
        bus = current_app.config.get("EVENT_BUS")
        if bus is not None:
            bus.publish(event_type, payload)
    except Exception as exc:                          # pragma: no cover
        log.warning("event publish failed: %s", exc)


def _get_owned_account(account_id: Optional[int]) -> Optional[BankAccount]:
    if not account_id:
        return None
    try:
        account_id = int(account_id)
    except (TypeError, ValueError):
        return None
    return BankAccount.query.filter_by(
        id=account_id, user_id=current_user.id
    ).first()


def _get_owned_card(card_id: Optional[int]) -> Optional[Card]:
    if not card_id:
        return None
    try:
        card_id = int(card_id)
    except (TypeError, ValueError):
        return None
    return Card.query.filter_by(id=card_id, user_id=current_user.id).first()


def _set_account_status(account_id: int, status: str):
    account = _get_owned_account(account_id)
    if account is None:
        return jsonify({"error": "account not found"}), 404
    account.status = status
    if status == 'active':
        account.closed_at = None
    db.session.commit()
    _publish("banking.account_status", {
        "account_id": account.id, "status": status, "user_id": current_user.id,
    })
    return jsonify({"success": True, "account": account.to_dict()})


def _set_card_status(card_id: int, status: str, reason: Optional[str]):
    card = _get_owned_card(card_id)
    if card is None:
        return jsonify({"error": "card not found"}), 404
    card.status = status
    card.blocked_reason = reason
    db.session.commit()
    _publish("banking.card_status", {
        "card_id": card.id, "status": status, "reason": reason,
        "user_id": current_user.id,
    })
    return jsonify({"success": True, "card": card.to_dict()})


def _unique_account_number(max_tries: int = 6) -> str:
    for _ in range(max_tries):
        candidate = utils.generate_account_number(12)
        if not BankAccount.query.filter_by(account_number=candidate).first():
            return candidate
    return utils.generate_account_number(14)


def _precheck_payment(
    card: Card, account: BankAccount, amount: float, country: str, is_card_present: bool,
) -> Optional[Tuple[str, str]]:
    """Return (decision, reason) if the payment must be rejected before the
    fraud model runs; ``None`` if it can proceed."""
    if card.status == 'blocked':
        return 'declined', 'card is blocked'
    if card.status == 'frozen':
        return 'declined', 'card is frozen'
    if card.is_expired:
        return 'declined', 'card is expired'
    if account.status != 'active':
        return 'declined', f'account is {account.status}'
    if amount > account.available_balance:
        return 'declined', 'insufficient funds'
    if amount > (card.daily_limit or 0) - (card.daily_spent or 0):
        return 'declined', 'daily card limit exceeded'
    if (country or '').upper() != (account.country or 'US').upper() and not card.international_enabled:
        return 'declined', 'international transactions disabled on this card'
    if not is_card_present and not card.online_enabled:
        return 'declined', 'online transactions disabled on this card'
    return None


def _record_declined(card, account, amount, country, category, merchant_name, device, hour,
                     is_card_present, decision: str, reason: str):
    """Persist a declined transaction without running the ML model."""
    txn_id = f"pay_{uuid.uuid4().hex[:16]}"
    record = TransactionRecord(
        transaction_id=txn_id,
        amount=amount,
        country=country,
        merchant_category=category,
        device_type=device,
        hour=hour,
        is_card_present=is_card_present,
        is_fraud=False,
        fraud_probability=0.0,
        risk_level='low',
        decision=decision,
        model_score=0.0,
        rule_score=0.0,
        triggered_rules=[{"name": "preflight", "weight": 0.0, "reason": reason}],
        latency_ms=0.0,
        processed_by=current_user.username,
        user_id=current_user.id,
        bank_account_id=account.id,
        card_id=card.id,
        merchant_name=merchant_name,
        currency=account.currency,
    )
    db.session.add(record)
    db.session.commit()
    _publish("banking.payment", {
        "transaction": record.to_dict(),
        "card": card.to_dict(),
        "account": account.to_dict(),
        "user_id": current_user.id,
        "preflight_failure": True,
    })
    return jsonify({
        "success": False, "decision": decision, "error": reason,
        "transaction": record.to_dict(),
    }), 402
