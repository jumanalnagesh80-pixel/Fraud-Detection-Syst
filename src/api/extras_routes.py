"""
Advanced API endpoints for analytics, reports, geographic data, and notifications.

Endpoints:
  GET  /api/countries                  list all supported countries
  GET  /api/countries/<code>           single country details + recent activity
  GET  /api/geo/fraud-map              fraud counts grouped by country
  GET  /api/geo/regional-stats         risk and volume stats per region

  GET  /api/reports/executive          executive summary for bankers
  GET  /api/reports/customer/<user_id> per-customer risk profile (synthetic)
  GET  /api/reports/top-risks          top risk indicators ranked

  GET  /api/notifications              recent notifications for current user
  POST /api/notifications/mark-read    mark all notifications as read
"""

from __future__ import annotations

import time
import random
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Dict, List

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from ..data_processing import countries as country_data


def create_extras_blueprint() -> Blueprint:
    bp = Blueprint("api_extras", __name__, url_prefix="/api")

    # ==================================================================
    # Countries / Geography
    # ==================================================================
    @bp.get("/countries")
    def list_countries():
        """List all supported countries with risk and currency info."""
        region = request.args.get("region")
        items = country_data.list_countries(region=region)
        return jsonify({
            "count": len(items),
            "regions": country_data.get_regions(),
            "countries": items,
        })

    @bp.get("/countries/<code>")
    def country_details(code: str):
        """Get details for a single country plus recent activity stats."""
        country = country_data.get_country(code)
        if not country:
            return jsonify({"error": "country not found"}), 404

        # gather recent activity for this country from in-memory monitor
        monitor = current_app.config.get("MONITOR")
        recent_country_txns = []
        country_fraud = 0
        country_total = 0
        if monitor is not None:
            for item in monitor.recent(500):
                t = item.get("transaction", {})
                if (t.get("country") or "").upper() == code.upper():
                    country_total += 1
                    r = item.get("result", {})
                    if r.get("decision") == "decline" or r.get("risk_level") == "critical":
                        country_fraud += 1
                    recent_country_txns.append(item)

        return jsonify({
            "country": {"code": code.upper(), **country},
            "is_high_risk": country_data.is_high_risk(code),
            "is_sanctioned": country_data.is_sanctioned(code),
            "stats": {
                "total_transactions": country_total,
                "flagged_transactions": country_fraud,
                "fraud_rate": round(country_fraud / country_total, 4) if country_total else 0.0,
            },
            "recent_transactions": recent_country_txns[:10],
        })

    @bp.get("/geo/fraud-map")
    def fraud_map():
        """Fraud counts by country across the live monitor window."""
        monitor = current_app.config.get("MONITOR")
        country_total: Counter = Counter()
        country_fraud: Counter = Counter()

        if monitor is not None:
            for item in monitor.recent(1000):
                t = item.get("transaction", {})
                code = (t.get("country") or "").upper()
                if not code:
                    continue
                country_total[code] += 1
                r = item.get("result", {})
                if r.get("risk_level") in ("high", "critical") or r.get("decision") == "decline":
                    country_fraud[code] += 1

        rows = []
        for code, total in country_total.most_common():
            country = country_data.get_country(code)
            if not country:
                continue
            fraud_count = country_fraud.get(code, 0)
            rows.append({
                "code": code,
                "name": country["name"],
                "flag": country["flag"],
                "region": country["region"],
                "total": total,
                "fraud": fraud_count,
                "fraud_rate": round(fraud_count / total, 4) if total else 0.0,
                "country_risk": country["risk"],
            })

        return jsonify({"countries": rows})

    @bp.get("/geo/regional-stats")
    def regional_stats():
        """Volume and fraud counts grouped by region."""
        monitor = current_app.config.get("MONITOR")
        region_total: Counter = Counter()
        region_fraud: Counter = Counter()

        if monitor is not None:
            for item in monitor.recent(1000):
                code = ((item.get("transaction") or {}).get("country") or "").upper()
                country = country_data.get_country(code)
                if not country:
                    continue
                region = country["region"]
                region_total[region] += 1
                r = item.get("result", {})
                if r.get("risk_level") in ("high", "critical") or r.get("decision") == "decline":
                    region_fraud[region] += 1

        rows = []
        for region in country_data.get_regions():
            total = region_total.get(region, 0)
            fraud = region_fraud.get(region, 0)
            rows.append({
                "region": region,
                "total": total,
                "fraud": fraud,
                "fraud_rate": round(fraud / total, 4) if total else 0.0,
            })
        rows.sort(key=lambda r: r["total"], reverse=True)
        return jsonify({"regions": rows})

    # ==================================================================
    # Reports
    # ==================================================================
    @bp.get("/reports/executive")
    def executive_summary():
        """High-level KPIs for bankers/executives."""
        monitor = current_app.config.get("MONITOR")
        alert_mgr = current_app.config.get("ALERTS")

        metrics = monitor.metrics() if monitor else {}
        alert_stats = alert_mgr.stats() if alert_mgr else {}

        total = metrics.get("total_transactions", 0)
        fraud = metrics.get("fraud_detected", 0)
        approved = metrics.get("approved", 0)
        avg_amount = 0.0
        total_amount = 0.0
        fraud_amount_blocked = 0.0

        if monitor:
            for item in monitor.recent(1000):
                t = item.get("transaction") or {}
                amount = float(t.get("amount") or 0)
                total_amount += amount
                r = item.get("result") or {}
                if r.get("decision") == "decline":
                    fraud_amount_blocked += amount
            if total:
                avg_amount = total_amount / max(1, len(monitor.recent(1000)))

        # crude estimated savings: blocked-fraud amount * 100 (annualized projection)
        estimated_annual_savings = round(fraud_amount_blocked * 100, 2)

        return jsonify({
            "summary": {
                "total_transactions": total,
                "fraud_detected": fraud,
                "approved": approved,
                "review_pending": metrics.get("review", 0),
                "declined": metrics.get("declined", 0),
                "fraud_rate": metrics.get("fraud_rate", 0.0),
                "avg_latency_ms": metrics.get("avg_latency_ms", 0.0),
                "uptime_seconds": metrics.get("uptime_seconds", 0),
            },
            "financials": {
                "total_volume_usd": round(total_amount, 2),
                "average_transaction_usd": round(avg_amount, 2),
                "fraud_amount_blocked_usd": round(fraud_amount_blocked, 2),
                "estimated_annual_savings_usd": estimated_annual_savings,
            },
            "alerts": {
                "by_level": alert_stats,
                "total": sum(alert_stats.values()) if alert_stats else 0,
            },
            "model": {
                "metrics": current_app.config["FRAUD_MODEL"].metrics_,
            },
            "generated_at": datetime.utcnow().isoformat(),
        })

    @bp.get("/reports/top-risks")
    def top_risks():
        """Top fraud-driving signals across recent transactions."""
        monitor = current_app.config.get("MONITOR")
        rule_counter: Counter = Counter()
        category_counter: Counter = Counter()
        device_counter: Counter = Counter()
        hour_counter: Counter = Counter()

        if monitor:
            for item in monitor.recent(1000):
                r = item.get("result") or {}
                t = item.get("transaction") or {}
                if r.get("risk_level") in ("high", "critical"):
                    for rule in r.get("triggered_rules", []) or []:
                        rule_counter[rule.get("name", "unknown")] += 1
                    if t.get("merchant_category"):
                        category_counter[t["merchant_category"]] += 1
                    if t.get("device_type"):
                        device_counter[t["device_type"]] += 1
                    if t.get("hour") is not None:
                        hour_counter[int(t["hour"])] += 1

        return jsonify({
            "top_rules": rule_counter.most_common(10),
            "top_categories": category_counter.most_common(10),
            "top_devices": device_counter.most_common(10),
            "fraud_by_hour": sorted(hour_counter.items()),
        })

    @bp.get("/reports/customer/<user_id>")
    def customer_profile(user_id: str):
        """Synthetic customer risk profile for analyst review."""
        monitor = current_app.config.get("MONITOR")

        txns: List[Dict] = []
        total_amount = 0.0
        fraud_count = 0
        countries_used: Counter = Counter()
        devices_used: Counter = Counter()
        categories_used: Counter = Counter()

        if monitor:
            for item in monitor.recent(1000):
                t = item.get("transaction") or {}
                if str(t.get("user_id")) == str(user_id):
                    txns.append(item)
                    total_amount += float(t.get("amount") or 0)
                    r = item.get("result") or {}
                    if r.get("risk_level") in ("high", "critical"):
                        fraud_count += 1
                    if t.get("country"):
                        countries_used[t["country"]] += 1
                    if t.get("device_type"):
                        devices_used[t["device_type"]] += 1
                    if t.get("merchant_category"):
                        categories_used[t["merchant_category"]] += 1

        if not txns:
            return jsonify({
                "user_id": user_id,
                "found": False,
                "message": "No recent activity for this customer",
            })

        n = len(txns)
        risk_score = round(min(1.0, fraud_count / max(1, n) * 2 + 0.05), 3)
        avg_amount = round(total_amount / n, 2)

        return jsonify({
            "user_id": user_id,
            "found": True,
            "summary": {
                "total_transactions": n,
                "total_amount_usd": round(total_amount, 2),
                "average_transaction_usd": avg_amount,
                "fraud_attempts": fraud_count,
                "calculated_risk_score": risk_score,
                "risk_level": country_data.get_risk_level(risk_score),
            },
            "behavior": {
                "countries": countries_used.most_common(5),
                "devices": devices_used.most_common(5),
                "categories": categories_used.most_common(5),
            },
            "recent_transactions": txns[-15:],
        })

    # ==================================================================
    # Notifications (in-memory, per-process for the demo)
    # ==================================================================
    @bp.get("/notifications")
    @login_required
    def list_notifications():
        """Get recent notifications for the current user."""
        store = _notification_store(current_app)
        items = store.get(current_user.id, [])
        # also include alerts as notifications if user opted in
        if getattr(current_user, "notify_high_risk", True):
            alert_mgr = current_app.config.get("ALERTS")
            if alert_mgr:
                alerts = alert_mgr.list_alerts(20)
                for a in alerts:
                    if getattr(current_user, "notify_critical_only", False) and a.get("risk_level") != "critical":
                        continue
                    items.append({
                        "id": f"alert_{a.get('transaction_id')}",
                        "type": "fraud_alert",
                        "level": a.get("risk_level"),
                        "title": f"Fraud alert: {a.get('transaction_id')}",
                        "message": (a.get("reasons") or ["Suspicious transaction"])[0],
                        "created_at": a.get("created_at"),
                        "read": False,
                    })
        # sort newest first
        items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        unread = sum(1 for i in items if not i.get("read"))
        return jsonify({
            "count": len(items),
            "unread": unread,
            "notifications": items[:30],
        })

    @bp.post("/notifications/mark-read")
    @login_required
    def mark_read():
        store = _notification_store(current_app)
        items = store.get(current_user.id, [])
        for n in items:
            n["read"] = True
        return jsonify({"success": True, "marked": len(items)})

    return bp


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _notification_store(app) -> Dict:
    """Simple per-app in-memory notification store keyed by user_id."""
    if "NOTIFICATIONS" not in app.config:
        app.config["NOTIFICATIONS"] = defaultdict(list)
    return app.config["NOTIFICATIONS"]


def push_notification(app, user_id: int, type_: str, title: str, message: str, level: str = "info"):
    """Helper that other modules can call to push a notification."""
    store = _notification_store(app)
    store[user_id].append({
        "id": f"{type_}_{int(time.time() * 1000)}_{random.randint(100, 999)}",
        "type": type_,
        "level": level,
        "title": title,
        "message": message,
        "created_at": datetime.utcnow().isoformat(),
        "read": False,
    })
    # cap queue per user
    if len(store[user_id]) > 100:
        store[user_id] = store[user_id][-100:]
