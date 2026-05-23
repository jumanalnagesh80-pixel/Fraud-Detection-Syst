"""
Fraud Detection System - main entry point.

Boots a Flask app that:
  1. Trains a fraud model on synthetic data at startup (a few seconds).
  2. Exposes a REST API under /api/...
  3. Serves the interactive dashboard at /
  4. Provides authentication, admin panel, and user management

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
from flask import Flask, send_from_directory, redirect, url_for
from flask_login import login_required, current_user
from flask_cors import CORS

from src.api import create_api_blueprint, create_extras_blueprint, create_sse_blueprint
from src.auth import init_auth
from src.auth.routes import auth_bp
from src.auth.middleware import init_rbac_middleware
from src.admin.routes import admin_bp
from src.banking import create_banking_blueprint, seed_user_banking
from src.database import db, init_db
from src.data_processing import generate_synthetic_transactions
from src.models import FraudModel
from src.real_time import AlertManager, EventBus, TransactionMonitor


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
    templates_dir = frontend_dir / "templates"
    
    app = Flask(
        __name__, 
        static_folder=str(frontend_dir), 
        static_url_path="",
        template_folder=str(templates_dir)
    )
    
    # Configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///fraud_detection.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'jwt-secret-key-change-in-production')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = 3600  # 1 hour

    # Upload settings (KYC ID-proof images)
    app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024  # 8 MB hard cap
    upload_dir = ROOT / "data" / "uploads" / "id_proofs"
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.config['ID_PROOF_UPLOAD_DIR'] = str(upload_dir)
    
    # Initialize extensions
    CORS(app)
    init_db(app)
    init_auth(app)
    init_rbac_middleware(app)
    
    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(create_api_blueprint())
    app.register_blueprint(create_extras_blueprint())
    app.register_blueprint(create_sse_blueprint())
    app.register_blueprint(create_banking_blueprint())
    
    # Initialize database and create default roles/admin
    with app.app_context():
        db.create_all()
        from src.auth.init_roles import init_default_roles, create_default_admin, ensure_user_columns
        try:
            ensure_user_columns()
            init_default_roles()
            create_default_admin()
            # Seed banking (account + card) for the default admin so the
            # banking page works out-of-the-box on a fresh install.
            from src.database.models import User as _User
            admin_user = _User.query.filter_by(username='admin').first()
            if admin_user is not None:
                seed_user_banking(admin_user)
                db.session.commit()
        except Exception as e:
            log.warning(f"Role/admin initialization: {e}")
            db.session.rollback()

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
    app.config["EVENT_BUS"] = EventBus(max_queue_size=200)

    # ------------------------------------------------------------------
    # frontend routes
    # ------------------------------------------------------------------
    @app.get("/")
    def index():
        """Redirect to login if not authenticated, else dashboard."""
        if current_user.is_authenticated:
            return redirect(url_for('main_dashboard'))
        return redirect(url_for('auth.login'))

    @app.get("/dashboard")
    @login_required
    def main_dashboard():
        """Main fraud detection dashboard."""
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/reports")
    @login_required
    def reports_page():
        """Banker analytics & reports page."""
        return send_from_directory(app.static_folder, "reports.html")

    @app.get("/transactions")
    @login_required
    def transactions_page():
        """User-facing transaction history page."""
        return send_from_directory(app.static_folder, "transactions.html")

    @app.get("/notifications")
    @login_required
    def notifications_page():
        """User notifications inbox."""
        return send_from_directory(app.static_folder, "notifications.html")

    @app.get("/banking")
    @login_required
    def banking_page():
        """User banking page (accounts, cards, payments)."""
        # Lazy seed: anyone landing on this page is guaranteed an account + card.
        try:
            seed_user_banking(current_user)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            log.warning("Banking seed failed for %s: %s", current_user.username, exc)
        return send_from_directory(app.static_folder, "banking.html")

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
