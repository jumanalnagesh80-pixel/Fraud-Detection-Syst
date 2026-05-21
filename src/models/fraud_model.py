"""
Fraud detection model.

A self-contained scikit-learn pipeline (RandomForest + GradientBoosting
ensemble via soft voting) combined with a rule engine. The class is
designed to train quickly on synthetic data so the API can boot up and
serve predictions immediately.
"""

from __future__ import annotations

import os
import pickle
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier, VotingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

from ..data_processing import FeatureEngineer, generate_synthetic_transactions
from .rule_engine import RuleEngine, RuleHit


@dataclass
class PredictionResult:
    transaction_id: str
    is_fraud: bool
    fraud_probability: float
    risk_level: str  # low / medium / high / critical
    model_score: float
    rule_score: float
    triggered_rules: List[Dict[str, Any]]
    decision: str  # approve / review / decline


class FraudModel:
    """Ensemble fraud classifier with rule augmentation."""

    THRESHOLDS = {
        "low": 0.0,
        "medium": 0.40,
        "high": 0.65,
        "critical": 0.85,
    }

    def __init__(self) -> None:
        self.feature_engineer = FeatureEngineer()
        self.rule_engine = RuleEngine()
        self.classifier: Optional[VotingClassifier] = None
        self.metrics_: Dict[str, float] = {}
        self.feature_importance_: Dict[str, float] = {}
        self.is_trained: bool = False

    # ------------------------------------------------------------------
    # training
    # ------------------------------------------------------------------
    def train(self, df: Optional[pd.DataFrame] = None) -> Dict[str, float]:
        """Train the ensemble and return evaluation metrics."""
        if df is None:
            df = generate_synthetic_transactions(n_transactions=8000, fraud_rate=0.05)

        y = df["is_fraud"].astype(int).values
        X = self.feature_engineer.fit_transform(df)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        rf = RandomForestClassifier(
            n_estimators=120, max_depth=10, class_weight="balanced",
            n_jobs=-1, random_state=42,
        )
        gb = GradientBoostingClassifier(n_estimators=100, max_depth=4, random_state=42)
        lr = LogisticRegression(max_iter=500, class_weight="balanced", random_state=42)

        self.classifier = VotingClassifier(
            estimators=[("rf", rf), ("gb", gb), ("lr", lr)],
            voting="soft",
            weights=[2, 2, 1],
        )
        self.classifier.fit(X_train, y_train)

        # metrics
        proba = self.classifier.predict_proba(X_test)[:, 1]
        preds = (proba >= 0.5).astype(int)
        self.metrics_ = {
            "accuracy": float(accuracy_score(y_test, preds)),
            "precision": float(precision_score(y_test, preds, zero_division=0)),
            "recall": float(recall_score(y_test, preds, zero_division=0)),
            "f1": float(f1_score(y_test, preds, zero_division=0)),
            "roc_auc": float(roc_auc_score(y_test, proba)),
            "training_samples": int(len(X_train)),
            "test_samples": int(len(X_test)),
        }

        # feature importance from the random forest
        try:
            rf_fitted = self.classifier.named_estimators_["rf"]
            importance = dict(zip(self.feature_engineer.FEATURE_COLUMNS, rf_fitted.feature_importances_))
            self.feature_importance_ = {k: float(v) for k, v in importance.items()}
        except Exception:
            self.feature_importance_ = {}

        self.is_trained = True
        return self.metrics_

    # ------------------------------------------------------------------
    # prediction
    # ------------------------------------------------------------------
    def predict(self, txn: Dict[str, Any]) -> PredictionResult:
        if not self.is_trained or self.classifier is None:
            raise RuntimeError("Model is not trained yet. Call .train() first.")

        features = self.feature_engineer.transform_single(txn)
        model_score = float(self.classifier.predict_proba(features)[0, 1])

        rule_score, rule_hits = self.rule_engine.evaluate(txn)

        # Combine: weighted sum of model probability and rule risk
        combined = 0.65 * model_score + 0.35 * rule_score
        combined = float(np.clip(combined, 0.0, 1.0))

        risk_level = self._risk_level(combined)
        decision = self._decision(combined)

        return PredictionResult(
            transaction_id=str(txn.get("transaction_id", "txn_unknown")),
            is_fraud=combined >= self.THRESHOLDS["high"],
            fraud_probability=round(combined, 4),
            risk_level=risk_level,
            model_score=round(model_score, 4),
            rule_score=round(rule_score, 4),
            triggered_rules=[
                {"name": h.name, "weight": h.weight, "reason": h.reason}
                for h in rule_hits
            ],
            decision=decision,
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _risk_level(self, score: float) -> str:
        if score >= self.THRESHOLDS["critical"]:
            return "critical"
        if score >= self.THRESHOLDS["high"]:
            return "high"
        if score >= self.THRESHOLDS["medium"]:
            return "medium"
        return "low"

    def _decision(self, score: float) -> str:
        if score >= self.THRESHOLDS["critical"]:
            return "decline"
        if score >= self.THRESHOLDS["high"]:
            return "review"
        return "approve"

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------
    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            pickle.dump(self, fh)

    @classmethod
    def load(cls, path: str) -> "FraudModel":
        with open(path, "rb") as fh:
            return pickle.load(fh)
