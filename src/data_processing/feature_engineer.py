"""
Feature engineering for transaction data.

Converts raw transaction records into numerical features suitable
for machine learning models.
"""

from __future__ import annotations

from typing import Dict, List, Any

import numpy as np
import pandas as pd


HIGH_RISK_COUNTRIES = {"NG", "RU", "CN"}
HIGH_RISK_CATEGORIES = {"gambling", "crypto", "wire_transfer", "atm_withdrawal"}


class FeatureEngineer:
    """Transform raw transaction dicts/dataframes into model features."""

    FEATURE_COLUMNS: List[str] = [
        "amount",
        "amount_log",
        "hour",
        "is_night",
        "is_weekend_proxy",
        "is_card_present",
        "high_risk_country",
        "high_risk_category",
        "is_online",
        "amount_zscore",
    ]

    def __init__(self) -> None:
        self.amount_mean_: float = 100.0
        self.amount_std_: float = 50.0
        self._fitted = False

    # ------------------------------------------------------------------
    # fit / transform
    # ------------------------------------------------------------------
    def fit(self, df: pd.DataFrame) -> "FeatureEngineer":
        if "amount" in df.columns:
            self.amount_mean_ = float(df["amount"].mean())
            self.amount_std_ = float(df["amount"].std() or 1.0)
        self._fitted = True
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        amount = df["amount"].astype(float)

        out["amount"] = amount
        out["amount_log"] = np.log1p(amount)
        out["hour"] = df["hour"].astype(int) if "hour" in df else 12
        out["is_night"] = ((out["hour"] < 6) | (out["hour"] >= 23)).astype(int)
        # weekend proxy: treat anything we don't know as 0
        out["is_weekend_proxy"] = 0
        out["is_card_present"] = df.get("is_card_present", False).astype(int)
        out["high_risk_country"] = df.get("country", "US").isin(HIGH_RISK_COUNTRIES).astype(int)
        out["high_risk_category"] = df.get("merchant_category", "grocery").isin(HIGH_RISK_CATEGORIES).astype(int)
        device = df.get("device_type", "web_chrome").astype(str)
        out["is_online"] = (~device.str.startswith(("pos_", "atm"))).astype(int)
        std = self.amount_std_ if self.amount_std_ else 1.0
        out["amount_zscore"] = (amount - self.amount_mean_) / std
        return out[self.FEATURE_COLUMNS]

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.fit(df).transform(df)

    # ------------------------------------------------------------------
    # helpers for single-record (real-time) scoring
    # ------------------------------------------------------------------
    def transform_single(self, txn: Dict[str, Any]) -> pd.DataFrame:
        return self.transform(pd.DataFrame([txn]))
