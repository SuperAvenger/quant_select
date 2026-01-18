from __future__ import annotations

from typing import Dict, List

import pandas as pd


def check_panel_quality(panel: pd.DataFrame, dates: List[str]) -> Dict:
    if panel.empty:
        return {"empty": True}

    quality: Dict[str, object] = {"empty": False}
    if isinstance(panel.index, pd.MultiIndex) and "trade_date" in panel.index.names:
        trade_dates = panel.index.get_level_values("trade_date").unique()
        trade_dates = trade_dates.astype(str).tolist()
        missing_dates = sorted(set(dates) - set(trade_dates))
        quality["missing_trade_dates"] = missing_dates
        quality["missing_trade_dates_count"] = len(missing_dates)
    else:
        quality["missing_trade_dates"] = []
        quality["missing_trade_dates_count"] = 0

    quality["duplicate_rows"] = int(panel.index.duplicated().sum())

    price_cols = [col for col in ["open", "high", "low", "close"] if col in panel.columns]
    if price_cols:
        price = panel[price_cols].apply(pd.to_numeric, errors="coerce")
        bad_price = (price <= 0).any(axis=1) | price.isna().any(axis=1)
        quality["bad_price_rows"] = int(bad_price.sum())
        if {"high", "low", "close"}.issubset(price.columns):
            invalid_ohlc = (price["high"] < price["low"]) | (
                (price["close"] > price["high"]) | (price["close"] < price["low"])
            )
            quality["invalid_ohlc_rows"] = int(invalid_ohlc.sum())
        else:
            quality["invalid_ohlc_rows"] = 0
    else:
        quality["bad_price_rows"] = 0
        quality["invalid_ohlc_rows"] = 0

    if {"up_limit", "down_limit"}.issubset(panel.columns):
        missing_limits = panel["up_limit"].isna() | panel["down_limit"].isna()
        quality["missing_limit_rows"] = int(missing_limits.sum())
    else:
        quality["missing_limit_rows"] = 0

    if "suspend" in panel.columns:
        missing_suspend = panel["suspend"].isna()
        quality["missing_suspend_rows"] = int(missing_suspend.sum())
    else:
        quality["missing_suspend_rows"] = 0

    return quality
