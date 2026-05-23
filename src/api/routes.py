"""
REST API routes.

Endpoints:
  POST /api/predict           score a single transaction
  POST /api/predict/batch     score a list of transactions
  GET  /api/transactions      recent transactions (rolling window)
  GET  /api/alerts            recent alerts
  GET  /api/metrics           live dashboard metrics
  GET  /api/model/info        training metrics + feature importance
  POST /api/simulate          generate N synthetic transactions and score them
  GET  /api/health            liveness probe
"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, Dict

from flask import Blueprint, current_app, jsonify, request

from ..data_processing import generate_synthetic_transactions


def create_api_blueprint() -> Blueprint:
    bp = Blueprint("api", __name__, url_prefix="/api")

    # ------------------------------------------------------------------
    # health
    # ------------------------------------------------------------------
    @bp.get("/health")
    def health():
        model = current_app.config["FRAUD_MODEL"]
        return jsonify({
            "status": "ok",
            "model_trained": model.is_trained,
            "version": "1.0.0",
        })

    # ------------------------------------------------------------------
    # single prediction
    # ------------------------------------------------------------------
    @bp.post("/predict")
    def predict():
        payload: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
        if "amount" not in payload:
            return jsonify({"error": "field 'amount' is required"}), 400

        result = _score_and_record(payload)
        return jsonify(result)

    # ------------------------------------------------------------------
    # batch prediction
    # ------------------------------------------------------------------
    @bp.post("/predict/batch")
    def predict_batch():
        payload = request.get_json(force=True, silent=True) or {}
        items = payload.get("transactions", [])
        if not isinstance(items, list):
            return jsonify({"error": "'transactions' must be a list"}), 400
        results = [_score_and_record(t) for t in items]
        return jsonify({"count": len(results), "results": results})

    # alias: matches README docs
    @bp.post("/batch-predict")
    def batch_predict_alias():
        return predict_batch()

    @bp.get("/statistics")
    def statistics_alias():
        return metrics()

    # ------------------------------------------------------------------
    # listings
    # ------------------------------------------------------------------
    @bp.get("/transactions")
    def transactions():
        monitor = current_app.config["MONITOR"]
        limit = int(request.args.get("limit", 50))
        return jsonify({"transactions": monitor.recent(limit)})

    @bp.get("/alerts")
    def alerts():
        alert_mgr = current_app.config["ALERTS"]
        limit = int(request.args.get("limit", 50))
        return jsonify({"alerts": alert_mgr.list_alerts(limit)})

    @bp.get("/metrics")
    def metrics():
        monitor = current_app.config["MONITOR"]
        alert_mgr = current_app.config["ALERTS"]
        data = monitor.metrics()
        data["alerts_by_level"] = alert_mgr.stats()
        return jsonify(data)

    @bp.get("/model/info")
    def model_info():
        model = current_app.config["FRAUD_MODEL"]
        return jsonify({
            "is_trained": model.is_trained,
            "metrics": model.metrics_,
            "feature_importance": model.feature_importance_,
            "thresholds": model.THRESHOLDS,
        })

    # ------------------------------------------------------------------
    # simulator (handy for the dashboard demo button)
    # ------------------------------------------------------------------
    @bp.post("/simulate")
    def simulate():
        payload = request.get_json(force=True, silent=True) or {}
        count = max(1, min(int(payload.get("count", 25)), 200))
        fraud_rate = float(payload.get("fraud_rate", 0.15))

        df = generate_synthetic_transactions(
            n_transactions=count, fraud_rate=fraud_rate, seed=None
        )
        results = [_score_and_record(row.to_dict()) for _, row in df.iterrows()]
        return jsonify({"count": len(results), "results": results})

    return bp


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _score_and_record(transaction: Dict[str, Any]) -> Dict[str, Any]:
    """Score one transaction, update monitor + alerts, return JSON dict."""
    model = current_app.config["FRAUD_MODEL"]
    monitor = current_app.config["MONITOR"]
    alert_mgr = current_app.config["ALERTS"]
    event_bus = current_app.config.get("EVENT_BUS")

    start = time.perf_counter()
    prediction = model.predict(transaction)
    latency_ms = (time.perf_counter() - start) * 1000.0

    result_dict = asdict(prediction)
    record = monitor.record(transaction, result_dict, latency_ms)

    alert = None
    if prediction.risk_level in {"high", "critical"}:
        alert = alert_mgr.raise_alert(
            transaction_id=prediction.transaction_id,
            risk_level=prediction.risk_level,
            fraud_probability=prediction.fraud_probability,
            decision=prediction.decision,
            reasons=[r["reason"] for r in prediction.triggered_rules],
        )

    # broadcast to any SSE subscribers so the dashboard updates in real time
    if event_bus is not None:
        event_bus.publish("transaction.scored", record)
        if alert is not None:
            event_bus.publish("transaction.alert", alert)

    return {
        "transaction": transaction,
        "result": result_dict,
        "latency_ms": round(latency_ms, 2),
    }
