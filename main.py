"""
Fraud Detection System - main entry point.

Boots a Flask app that:
  1. Trains a fraud model on synthetic data at startup (a few seconds).
  2. Exposes a REST API under /api/...
  3. Serves the interactive dashboard at /

Usage:
    # start the web dashboard + API (default)
    python main.py
    python main.py --mode webapp

    # generate a synthetic dataset
    python main.py --mode generate --samples 10000

    # train and save a model
    python main.py --mode train --data data/synthetic/synthetic_transactions.csv

    # production
    gunicorn main:app -b 0.0.0.0:5000
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import pandas as pd
from flask import Flask, send_from_directory

from src.api import create_api_blueprint
from src.data_processing import generate_synthetic_transactions
from src.models import FraudModel
from src.real_time import AlertManager, TransactionMonitor


ROOT = Path(__file__).parent
MODEL_PATH = ROOT / "models" / "trained" / "fraud_model.pkl"
SYNTHETIC_PATH = ROOT / "data" / "synthetic" / "synthetic_transactions.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("fraud-detection")


# ----------------------------------------------------------------------
# app factory
# ----------------------------------------------------------------------
def create_app() -> Flask:
    frontend_dir = ROOT / "frontend"
    app = Flask(__name__, static_folder=str(frontend_dir), static_url_path="")

    # try to load a pre-trained model first
    model = FraudModel()
    if MODEL_PATH.exists():
        try:
            log.info("Loading pre-trained model from %s", MODEL_PATH)
            model = FraudModel.load(str(MODEL_PATH))
        except Exception as e:
            log.warning("Failed to load saved model (%s); training fresh.", e)
            model = FraudModel()

    if not model.is_trained:
        log.info("Training fraud detection model on synthetic data...")
        metrics = model.train()
        log.info(
            "Model trained | accuracy=%.3f precision=%.3f recall=%.3f roc_auc=%.3f",
            metrics["accuracy"], metrics["precision"], metrics["recall"], metrics["roc_auc"],
        )

    app.config["FRAUD_MODEL"] = model
    app.config["MONITOR"] = TransactionMonitor(window_size=500)
    app.config["ALERTS"] = AlertManager(max_alerts=200)

    app.register_blueprint(create_api_blueprint())

    # ------------------------------------------------------------------
    # frontend routes
    # ------------------------------------------------------------------
    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/dashboard")
    def dashboard_alias():
        return send_from_directory(app.static_folder, "index.html")

    return app


# ----------------------------------------------------------------------
# CLI commands
# ----------------------------------------------------------------------
def cmd_generate(samples: int, fraud_rate: float, output: Path) -> None:
    log.info("Generating %d synthetic transactions (fraud_rate=%.2f)...", samples, fraud_rate)
    df = generate_synthetic_transactions(n_transactions=samples, fraud_rate=fraud_rate)
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False)
    log.info("Wrote %s rows -> %s", len(df), output)


def cmd_train(data: Path, output: Path) -> None:
    if data and data.exists():
        log.info("Loading training data from %s", data)
        df = pd.read_csv(data)
    else:
        log.info("No data file given; generating synthetic data on the fly.")
        df = generate_synthetic_transactions(n_transactions=8000, fraud_rate=0.05)

    model = FraudModel()
    metrics = model.train(df)
    log.info("Training complete:")
    for k, v in metrics.items():
        log.info("  %-20s %s", k, v)

    output.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(output))
    log.info("Saved model -> %s", output)


def cmd_webapp(host: str, port: int) -> None:
    app = create_app()
    log.info("Starting Sentinel dashboard on http://%s:%d (press Ctrl+C to stop)", host, port)
    app.run(host=host, port=port, debug=False)


# ----------------------------------------------------------------------
# entry
# ----------------------------------------------------------------------
def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Sentinel Fraud Detection System")
    p.add_argument("--mode", choices=["webapp", "generate", "train"], default="webapp")
    p.add_argument("--samples", type=int, default=10000)
    p.add_argument("--fraud-rate", type=float, default=0.05)
    p.add_argument("--data", type=Path, default=SYNTHETIC_PATH)
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5000)))
    return p.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    if args.mode == "generate":
        cmd_generate(
            samples=args.samples,
            fraud_rate=args.fraud_rate,
            output=args.output or SYNTHETIC_PATH,
        )
    elif args.mode == "train":
        cmd_train(
            data=args.data,
            output=args.output or MODEL_PATH,
        )
    else:
        cmd_webapp(host=args.host, port=args.port)


# Module-level `app` for gunicorn (`gunicorn main:app`).
# We only auto-build the app when imported by a WSGI server, never during
# CLI invocations (which would otherwise train the model twice).
app = None
if __name__ != "__main__" and os.environ.get("FRAUD_AUTOLOAD") == "1":
    app = create_app()


if __name__ == "__main__":
    main(sys.argv[1:])
