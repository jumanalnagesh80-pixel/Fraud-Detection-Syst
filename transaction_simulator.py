"""
Transaction simulator.

Generates realistic transactions and POSTs them to the fraud detection
API. Useful for stress testing and demoing the dashboard without real
traffic.

Usage:
    # built-in offline demo (no API needed)
    python transaction_simulator.py --mode demo

    # send a continuous stream to the API
    python transaction_simulator.py --mode stream --rate 5 --duration 60

    # burst attack (lots of high-risk transactions)
    python transaction_simulator.py --mode burst --count 50
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from typing import Any, Dict

try:
    import requests  # type: ignore
except ImportError:
    requests = None  # demo mode still works

from src.data_processing import generate_synthetic_transactions
from src.models import FraudModel


# ----------------------------------------------------------------------
# offline demo (no API required)
# ----------------------------------------------------------------------
def demo_mode() -> None:
    print("=" * 70)
    print("  Sentinel Fraud Detection - Offline Demo")
    print("=" * 70)
    print("\nTraining model on synthetic data...")
    model = FraudModel()
    metrics = model.train()
    for k, v in metrics.items():
        print(f"  {k:>20s}: {v}")

    print("\nScoring 10 sample transactions:\n")
    df = generate_synthetic_transactions(n_transactions=10, fraud_rate=0.4, seed=None)
    for _, row in df.iterrows():
        txn = row.to_dict()
        result = model.predict(txn)
        marker = "[FRAUD]" if result.is_fraud else "[ OK  ]"
        print(
            f"  {marker} {result.transaction_id} | "
            f"${txn['amount']:>8.2f} | {txn['country']:>2} | {txn['merchant_category']:<14} | "
            f"risk={result.risk_level:<8} prob={result.fraud_probability:.2%} -> {result.decision}"
        )
    print()


# ----------------------------------------------------------------------
# API-driven modes
# ----------------------------------------------------------------------
def _check_requests() -> None:
    if requests is None:
        print("ERROR: `requests` is required for stream/burst modes. Install it: pip install requests", file=sys.stderr)
        sys.exit(1)


def stream_mode(api_url: str, rate: float, duration: int) -> None:
    _check_requests()
    print(f"Streaming ~{rate} tx/s to {api_url} for {duration}s...")
    end = time.time() + duration
    delay = 1.0 / max(rate, 0.1)
    sent = 0
    fraud = 0
    while time.time() < end:
        df = generate_synthetic_transactions(n_transactions=1, fraud_rate=0.05, seed=None)
        txn = df.iloc[0].to_dict()
        ok, is_fraud = _post(api_url + "/api/predict", txn)
        sent += int(ok)
        fraud += int(is_fraud)
        time.sleep(delay)
    print(f"Done. Sent {sent} transactions, {fraud} flagged as fraud.")


def burst_mode(api_url: str, count: int) -> None:
    _check_requests()
    print(f"Sending burst of {count} high-risk transactions to {api_url}...")
    df = generate_synthetic_transactions(n_transactions=count, fraud_rate=0.5, seed=None)
    fraud = 0
    for _, row in df.iterrows():
        ok, is_fraud = _post(api_url + "/api/predict", row.to_dict())
        fraud += int(is_fraud)
    print(f"Burst complete. Detected {fraud}/{count} as fraud.")


def _post(url: str, payload: Dict[str, Any]) -> tuple[bool, bool]:
    try:
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code == 200:
            data = r.json()
            return True, bool(data.get("result", {}).get("is_fraud"))
    except Exception as e:
        print(f"  ! request failed: {e}", file=sys.stderr)
    return False, False


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Fraud detection transaction simulator")
    parser.add_argument("--mode", choices=["demo", "stream", "burst"], default="demo")
    parser.add_argument("--api", default="http://localhost:5000", help="Base URL of the API")
    parser.add_argument("--rate", type=float, default=5.0, help="Transactions per second (stream)")
    parser.add_argument("--duration", type=int, default=60, help="Stream duration in seconds")
    parser.add_argument("--count", type=int, default=50, help="Number of transactions (burst)")
    args = parser.parse_args()

    random.seed()

    if args.mode == "demo":
        demo_mode()
    elif args.mode == "stream":
        stream_mode(args.api, args.rate, args.duration)
    elif args.mode == "burst":
        burst_mode(args.api, args.count)


if __name__ == "__main__":
    main()
