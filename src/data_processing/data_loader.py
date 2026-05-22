"""
Data loader and synthetic transaction generator.

Generates realistic transaction datasets that mimic real-world banking
patterns, including legitimate purchases and various fraud scenarios.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import numpy as np
import pandas as pd

from .countries import COUNTRIES as ALL_COUNTRIES, HIGH_RISK_COUNTRIES as ALL_HIGH_RISK


MERCHANT_CATEGORIES = [
    "grocery", "restaurant", "fuel", "online_retail", "electronics",
    "travel", "entertainment", "healthcare", "utilities", "atm_withdrawal",
    "luxury", "gambling", "crypto", "wire_transfer",
]

# A representative subset for synthetic data generation (full list: countries.py)
COUNTRIES = [
    "US", "CA", "GB", "DE", "FR", "IT", "ES", "NL", "CH", "SE",
    "IN", "CN", "JP", "KR", "SG", "HK", "AU", "NZ", "BR", "MX",
    "AR", "AE", "SA", "IL", "ZA", "NG", "EG", "RU", "TR", "PL",
]
HIGH_RISK_COUNTRIES = ALL_HIGH_RISK

DEVICE_TYPES = ["mobile_ios", "mobile_android", "web_chrome", "web_firefox", "web_safari", "pos_terminal", "atm"]


def _random_timestamp(days_back: int = 30) -> datetime:
    """Random timestamp within the last `days_back` days."""
    seconds_back = random.randint(0, days_back * 24 * 3600)
    return datetime.utcnow() - timedelta(seconds=seconds_back)


def _generate_legitimate_transaction(user_id: str) -> Dict[str, Any]:
    """Generate a normal-looking transaction for a user."""
    category = random.choices(
        MERCHANT_CATEGORIES,
        weights=[18, 16, 12, 14, 8, 6, 7, 5, 8, 4, 1, 0, 0, 1],
        k=1,
    )[0]

    # amount distribution by category
    if category in {"grocery", "restaurant", "fuel"}:
        amount = round(np.random.gamma(2.0, 25.0), 2)
    elif category in {"electronics", "luxury", "travel"}:
        amount = round(np.random.gamma(3.0, 120.0), 2)
    else:
        amount = round(np.random.gamma(2.5, 40.0), 2)

    return {
        "transaction_id": f"txn_{random.randint(10**9, 10**10 - 1)}",
        "user_id": user_id,
        "amount": min(amount, 5000.0),
        "currency": "USD",
        "merchant_category": category,
        "country": random.choice(COUNTRIES),
        "device_type": random.choice(DEVICE_TYPES),
        "is_card_present": random.random() < 0.55,
        "hour": random.choices(range(24), weights=_normal_hour_weights(), k=1)[0],
        "timestamp": _random_timestamp().isoformat(),
        "is_fraud": 0,
    }


def _generate_fraudulent_transaction(user_id: str) -> Dict[str, Any]:
    """Generate a transaction that resembles known fraud patterns."""
    pattern = random.choice(["high_amount", "foreign_country", "odd_hour", "rapid_succession", "high_risk_merchant"])

    base = _generate_legitimate_transaction(user_id)

    if pattern == "high_amount":
        base["amount"] = round(random.uniform(2000, 15000), 2)
    elif pattern == "foreign_country":
        base["country"] = random.choice(list(HIGH_RISK_COUNTRIES))
        base["is_card_present"] = False
    elif pattern == "odd_hour":
        base["hour"] = random.choice([0, 1, 2, 3, 4])
        base["amount"] = round(random.uniform(500, 4000), 2)
    elif pattern == "rapid_succession":
        base["amount"] = round(random.uniform(100, 800), 2)
        base["merchant_category"] = "online_retail"
    elif pattern == "high_risk_merchant":
        base["merchant_category"] = random.choice(["gambling", "crypto", "wire_transfer"])
        base["amount"] = round(random.uniform(800, 6000), 2)

    base["is_fraud"] = 1
    return base


def _normal_hour_weights() -> List[float]:
    """Weights peaking during the day, dipping at night."""
    weights = []
    for h in range(24):
        if 8 <= h <= 21:
            weights.append(6.0)
        elif 6 <= h <= 7 or 22 <= h <= 23:
            weights.append(2.5)
        else:
            weights.append(0.6)
    return weights


def generate_synthetic_transactions(
    n_transactions: int = 10000,
    fraud_rate: float = 0.02,
    n_users: int = 500,
    seed: Optional[int] = 42,
) -> pd.DataFrame:
    """
    Generate a synthetic transaction dataset.

    Args:
        n_transactions: total number of transactions.
        fraud_rate: proportion of fraudulent transactions (0..1).
        n_users: distinct user accounts.
        seed: random seed for reproducibility.

    Returns:
        DataFrame with transaction records.
    """
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)

    user_ids = [f"user_{i:05d}" for i in range(n_users)]
    n_fraud = int(n_transactions * fraud_rate)
    n_legit = n_transactions - n_fraud

    rows: List[Dict[str, Any]] = []
    for _ in range(n_legit):
        rows.append(_generate_legitimate_transaction(random.choice(user_ids)))
    for _ in range(n_fraud):
        rows.append(_generate_fraudulent_transaction(random.choice(user_ids)))

    df = pd.DataFrame(rows)
    df = df.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    return df


def load_transactions(path: Optional[str] = None) -> pd.DataFrame:
    """
    Load transactions from a CSV file or fall back to synthetic data.
    """
    if path:
        try:
            return pd.read_csv(path)
        except FileNotFoundError:
            pass
    return generate_synthetic_transactions()
