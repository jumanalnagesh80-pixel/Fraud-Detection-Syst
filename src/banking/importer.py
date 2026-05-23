"""
Bank statement CSV importer.

Parses a wide range of bank statement formats and feeds each
transaction through the fraud engine. Designed to handle real-world
messy data — different date formats, debit/credit columns, dirty
merchant strings — without crashing.

Used by the ``/api/banking/import/statement`` endpoint.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.database import db
from src.database.models import BankAccount, Card, TransactionRecord


log = logging.getLogger(__name__)

# Hard cap to keep memory and DB usage sane on the demo.
MAX_ROWS_PER_IMPORT = 5000


# ---------------------------------------------------------------------
# Column detection
# ---------------------------------------------------------------------
# Map of common column names (case-insensitive, normalized) to canonical roles.
COLUMN_ALIASES = {
    "date":         {"date", "transaction date", "posting date", "post date",
                     "transaction_date", "txn date", "value date", "trans date"},
    "description":  {"description", "details", "particulars", "narration",
                     "memo", "merchant", "payee", "transaction details",
                     "transaction description", "name"},
    "amount":       {"amount", "amount (usd)", "transaction amount", "value",
                     "amt", "txn amount"},
    "debit":        {"debit", "debit amount", "withdrawal", "withdrawal amt",
                     "withdrawals", "spent", "money out", "dr"},
    "credit":       {"credit", "credit amount", "deposit", "deposit amt",
                     "deposits", "received", "money in", "cr"},
    "category":     {"category", "type", "transaction type", "merchant category"},
    "balance":      {"balance", "running balance", "available balance"},
}


def _normalize(s: str) -> str:
    """Lowercase + strip + collapse whitespace for column-name matching."""
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def detect_columns(header: List[str]) -> Dict[str, int]:
    """Map canonical column names → header index. Missing entries are absent."""
    mapping: Dict[str, int] = {}
    for idx, raw in enumerate(header):
        norm = _normalize(raw)
        for canonical, aliases in COLUMN_ALIASES.items():
            if canonical in mapping:
                continue
            if norm in aliases:
                mapping[canonical] = idx
                break
    return mapping


# ---------------------------------------------------------------------
# Date parsing — try a few common formats
# ---------------------------------------------------------------------
DATE_FORMATS = [
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
    "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
    "%m-%d-%Y", "%m/%d/%Y", "%m.%d.%Y",
    "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y",
    "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M",
]


def parse_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip().strip('"').strip("'")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def parse_amount(s: str) -> Optional[float]:
    """Strip currency symbols, commas, spaces, parens; return signed float."""
    if s is None:
        return None
    raw = str(s).strip()
    if not raw:
        return None
    # Parentheses commonly indicate negatives in finance ("(25.00)")
    negative = False
    if raw.startswith("(") and raw.endswith(")"):
        negative = True
        raw = raw[1:-1]
    # Strip any non-numeric characters except .,- and digits
    raw = re.sub(r"[^\d\.\,\-]", "", raw)
    # If both '.' and ',' are present, assume ',' is thousand-sep (US-style)
    if "," in raw and "." in raw:
        raw = raw.replace(",", "")
    elif "," in raw and "." not in raw:
        # comma-as-decimal? only treat as decimal if there's exactly one comma
        # and a sensible 2-3 digit fractional part
        if raw.count(",") == 1 and len(raw.split(",")[1]) <= 3:
            raw = raw.replace(",", ".")
        else:
            raw = raw.replace(",", "")
    try:
        v = float(raw)
    except ValueError:
        return None
    return -v if negative else v


# ---------------------------------------------------------------------
# Merchant + category inference
# ---------------------------------------------------------------------
# Crude keyword → category map. Matches the categories the fraud rule
# engine already understands. Keywords are matched case-insensitively
# against the cleaned-up description.
MERCHANT_CATEGORIES = [
    ("restaurant",     ["starbucks", "mcdonald", "kfc", "subway", "chipotle",
                        "domino", "pizza", "cafe", "coffee", "restaurant",
                        "diner", "grill", "kitchen", "bistro", "bakery",
                        "swiggy", "zomato", "doordash", "uber eats", "ubereats"]),
    ("grocery",        ["walmart", "target", "costco", "whole foods",
                        "trader joe", "safeway", "kroger", "supermarket",
                        "grocery", "bigbasket", "blinkit", "instacart"]),
    ("fuel",           ["shell", "chevron", "exxon", "bp ", "petrol", "fuel",
                        "gas station", "mobil", "indianoil", "hpcl", "iocl"]),
    ("online_retail",  ["amazon", "amzn", "flipkart", "ebay", "etsy", "shein",
                        "myntra", "ajio", "shopify", "alibaba", "aliexpress"]),
    ("electronics",    ["best buy", "apple store", "apple.com", "samsung",
                        "croma", "reliance digital", "newegg"]),
    ("travel",         ["uber", "lyft", "ola", "rapido", "airline", "delta",
                        "united", "american airlines", "klm", "emirates",
                        "hotel", "marriott", "hilton", "hyatt", "airbnb",
                        "booking.com", "expedia", "irctc", "makemytrip",
                        "redbus", "amtrak"]),
    ("entertainment",  ["netflix", "spotify", "hulu", "disney+", "prime video",
                        "youtube", "apple music", "hbo", "cinema", "movie",
                        "theatre", "theater", "playstation", "xbox", "steam"]),
    ("healthcare",     ["pharmacy", "cvs", "walgreens", "apollo", "medplus",
                        "hospital", "clinic", "dental", "doctor", "1mg",
                        "pharmeasy"]),
    ("utilities",      ["pg&e", "electric", "water", "gas company", "verizon",
                        "at&t", "t-mobile", "comcast", "xfinity", "spectrum",
                        "internet", "broadband", "airtel", "jio", "vi ",
                        "vodafone", "bsnl"]),
    ("atm_withdrawal", ["atm", "cash withdrawal", "cash wd"]),
    ("wire_transfer",  ["wire", "swift", "neft", "imps", "rtgs", "ach",
                        "transfer to", "external transfer"]),
    ("crypto",         ["coinbase", "binance", "kraken", "wazirx", "crypto",
                        "bitcoin", "ethereum", "btc"]),
    ("gambling",       ["casino", "betting", "poker", "lottery", "draftkings",
                        "fanduel", "dream11", "rummy"]),
    ("luxury",         ["louis vuitton", "gucci", "rolex", "tiffany",
                        "hermes", "prada"]),
]


def clean_merchant(raw: str) -> str:
    """Strip transaction-detail noise (POS codes, locations, ref numbers)."""
    if not raw:
        return ""
    s = raw.strip()
    # drop trailing ref numbers like "AMAZON US*MK7Q56KH3"
    s = re.split(r"\s{2,}|\*", s)[0]
    # collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    # cap length
    return s[:120]


def infer_category(description: str) -> str:
    desc = (description or "").lower()
    for category, keywords in MERCHANT_CATEGORIES:
        for kw in keywords:
            if kw in desc:
                return category
    return "online_retail"  # generic fallback


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------
def import_statement_csv(*, app, user_id: int, account: BankAccount,
                         card: Optional[Card], csv_text: str,
                         country_default: str = "US") -> Dict[str, Any]:
    """Parse a CSV statement and score each row through the fraud engine.

    Returns a summary dict for the API response. Persists every parsed
    transaction as a ``TransactionRecord`` with ``processed_by='csv_import'``
    so it shows up in the dashboard, alerts, admin panel, etc.
    """
    model = app.config.get("FRAUD_MODEL")
    monitor = app.config.get("MONITOR")
    alert_mgr = app.config.get("ALERTS")
    bus = app.config.get("EVENT_BUS")

    if model is None or not model.is_trained:
        raise RuntimeError("Fraud model is not loaded — try restarting the app")

    rows = list(_iter_csv(csv_text))
    if not rows:
        raise ValueError("CSV is empty or unreadable")
    if len(rows) > MAX_ROWS_PER_IMPORT + 5:  # +5 for header tolerance
        raise ValueError(f"CSV has too many rows (>{MAX_ROWS_PER_IMPORT}); "
                         "split it into smaller files")

    header = rows[0]
    cols = detect_columns(header)
    if "date" not in cols or "description" not in cols:
        raise ValueError("Could not find date and description columns in CSV. "
                         "Make sure the first row is a header (e.g. "
                         "'Date,Description,Amount').")
    if "amount" not in cols and ("debit" not in cols and "credit" not in cols):
        raise ValueError("Could not find amount columns. Need either an "
                         "'Amount' column, or 'Debit' and 'Credit' columns.")

    summary = {
        "rows_total": 0,
        "imported": 0,
        "skipped": 0,
        "fraud_detected": 0,
        "by_risk": {"low": 0, "medium": 0, "high": 0, "critical": 0},
        "decisions": {"approved": 0, "held_for_review": 0, "declined": 0},
        "total_amount": 0.0,
        "errors": [],
        "imported_transactions": [],   # last 50 for the summary modal
    }

    country = (account.country or country_default).upper()

    for line_no, row in enumerate(rows[1:], start=2):
        summary["rows_total"] += 1
        if not any((c or "").strip() for c in row):
            summary["skipped"] += 1
            continue
        try:
            txn = _row_to_txn(row, cols, account=account, card=card,
                              country=country)
        except Exception as exc:
            summary["skipped"] += 1
            if len(summary["errors"]) < 10:
                summary["errors"].append(f"line {line_no}: {exc}")
            continue
        if txn is None:
            summary["skipped"] += 1
            continue

        record = _score_and_persist(
            app=app, model=model, monitor=monitor, alert_mgr=alert_mgr,
            bus=bus, user_id=user_id, account=account, card=card, txn=txn,
        )
        if record is None:
            summary["skipped"] += 1
            continue

        summary["imported"] += 1
        summary["total_amount"] += float(record.amount or 0)
        summary["by_risk"][record.risk_level] = (
            summary["by_risk"].get(record.risk_level, 0) + 1
        )
        summary["decisions"][record.decision] = (
            summary["decisions"].get(record.decision, 0) + 1
        )
        if record.risk_level in ("high", "critical"):
            summary["fraud_detected"] += 1
        if len(summary["imported_transactions"]) < 50:
            summary["imported_transactions"].append(record.to_dict())

    summary["total_amount"] = round(summary["total_amount"], 2)
    return summary


# ---------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------
def _iter_csv(text: str) -> Iterable[List[str]]:
    """Sniff the dialect, yield rows as string lists."""
    text = text.lstrip("\ufeff")  # strip BOM if present
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    yield from reader


def _row_to_txn(row: List[str], cols: Dict[str, int], *,
                account: BankAccount, card: Optional[Card],
                country: str) -> Optional[Dict[str, Any]]:
    """Pull canonical fields out of a row. Skip non-debit lines."""
    def _g(name: str) -> str:
        idx = cols.get(name)
        return row[idx].strip() if idx is not None and idx < len(row) else ""

    date_str = _g("date")
    when = parse_date(date_str)
    if when is None:
        return None  # unparseable row

    description = clean_merchant(_g("description"))

    # Resolve amount + decide whether this is a debit (we score debits)
    if "debit" in cols or "credit" in cols:
        debit_v = parse_amount(_g("debit")) if "debit" in cols else None
        credit_v = parse_amount(_g("credit")) if "credit" in cols else None
        if debit_v and debit_v != 0:
            amount = abs(debit_v)
        elif credit_v and credit_v != 0:
            return None  # ignore deposits/credits — only score outflows
        else:
            return None
    else:
        signed = parse_amount(_g("amount"))
        if signed is None:
            return None
        # Most banks: negative = money out (debit). Some: positive = debit.
        # For fraud scoring we always want the spent amount as a positive.
        if signed < 0:
            amount = abs(signed)
        elif signed > 0:
            # A purely positive value with no debit/credit hint is ambiguous.
            # Treat it as a debit so we still score it (vs. skipping silently).
            amount = signed
        else:
            return None
    if amount <= 0:
        return None

    # Heuristic category from the description
    category = infer_category(description)

    # Heuristic device — banks rarely export this; default reasonable values
    is_card_present = category in ("restaurant", "fuel", "grocery",
                                   "atm_withdrawal", "luxury")

    return {
        "amount": float(amount),
        "country": country,
        "merchant_name": description or "Unknown Merchant",
        "merchant_category": category,
        "device_type": "pos_terminal" if is_card_present else "web_chrome",
        "is_card_present": is_card_present,
        "hour": when.hour,
        "occurred_at": when,
    }


def _score_and_persist(*, app, model, monitor, alert_mgr, bus, user_id: int,
                       account: BankAccount, card: Optional[Card],
                       txn: Dict[str, Any]) -> Optional[TransactionRecord]:
    """Run the fraud model on one row and persist the result."""
    txn_id = f"csv_{uuid.uuid4().hex[:14]}"
    scoring_input = {
        "transaction_id": txn_id,
        "user_id": str(user_id),
        "amount": txn["amount"],
        "currency": account.currency,
        "country": txn["country"],
        "merchant_category": txn["merchant_category"],
        "merchant_name": txn["merchant_name"],
        "hour": txn["hour"],
        "device_type": txn["device_type"],
        "is_card_present": txn["is_card_present"],
        "card_last4": (card.last4 if card else None),
        "card_brand": (card.brand if card else None),
    }

    start = time.perf_counter()
    try:
        prediction = model.predict(scoring_input)
    except Exception as exc:                            # pragma: no cover
        log.warning("CSV row scoring failed: %s", exc)
        return None
    latency_ms = (time.perf_counter() - start) * 1000.0
    result_dict = asdict(prediction)

    record = TransactionRecord(
        transaction_id=txn_id,
        amount=txn["amount"],
        country=txn["country"],
        merchant_category=txn["merchant_category"],
        device_type=txn["device_type"],
        hour=txn["hour"],
        is_card_present=txn["is_card_present"],
        is_fraud=prediction.is_fraud,
        fraud_probability=prediction.fraud_probability,
        risk_level=prediction.risk_level,
        # imported transactions are ALWAYS recorded as-is — we are scoring
        # them after the fact, not deciding to approve/decline them.
        decision=prediction.decision if prediction.decision != "approve"
                  else "approved",
        model_score=prediction.model_score,
        rule_score=prediction.rule_score,
        triggered_rules=result_dict.get("triggered_rules", []),
        latency_ms=latency_ms,
        processed_by="csv_import",
        processed_at=txn["occurred_at"],
        user_id=user_id,
        bank_account_id=account.id,
        card_id=(card.id if card else None),
        merchant_name=txn["merchant_name"],
        currency=account.currency,
    )
    db.session.add(record)
    db.session.commit()

    # Feed the live monitor + alerts so the dashboard reflects imports
    if monitor is not None:
        try:
            monitor.record(scoring_input, result_dict, latency_ms)
        except Exception:                               # pragma: no cover
            pass
    if prediction.risk_level in {"high", "critical"} and alert_mgr is not None:
        try:
            alert_mgr.raise_alert(
                transaction_id=txn_id,
                risk_level=prediction.risk_level,
                fraud_probability=prediction.fraud_probability,
                decision=record.decision,
                reasons=[r["reason"] for r in result_dict.get("triggered_rules", [])],
            )
        except Exception:                               # pragma: no cover
            pass
    if bus is not None:
        try:
            bus.publish("banking.payment", {
                "transaction": record.to_dict(),
                "card": (card.to_dict() if card else None),
                "account": account.to_dict(),
                "user_id": user_id,
                "imported": True,
            })
        except Exception:                               # pragma: no cover
            pass
    return record
