from __future__ import annotations

from typing import Dict, Tuple

import pandas as pd

from quant_a.features.indicators import (
    atr,
    ret,
    rolling_max,
    rolling_min,
    rolling_vol,
    rsi,
    sma,
)


def precompute_features(panel: pd.DataFrame, cfg: Dict) -> pd.DataFrame:
    if panel.empty:
        return panel
    strategy_cfg = cfg.get("strategy", {})
    strategy_name = str(strategy_cfg.get("name", "momentum_breakout"))
    entry_cfg = strategy_cfg.get("entry", {})
    exit_cfg = strategy_cfg.get("exit", {})
    ranking_cfg = strategy_cfg.get("ranking", {})

    trend_ma_days = int(entry_cfg.get("trend_ma_days", 0))
    ma_stop_days = int(exit_cfg.get("ma_stop_days", 0))
    atr_days = int(exit_cfg.get("atr_days", 0))
    breakout_lookback = int(entry_cfg.get("breakout_lookback", 0))
    mean_revert_ma_days = int(exit_cfg.get("mean_revert_ma_days", 0))

    by_code = panel.groupby(level="ts_code", group_keys=False)

    if trend_ma_days > 0:
        panel["ma_trend"] = by_code["close"].transform(lambda s: sma(s, trend_ma_days))
    if ma_stop_days > 0:
        panel["ma_stop"] = by_code["close"].transform(lambda s: sma(s, ma_stop_days))
    if atr_days > 0:
        panel["atr"] = by_code.apply(
            lambda df: atr(df["high"], df["low"], df["close"], atr_days)
        )
    if breakout_lookback > 0:
        rolling_high = by_code["high"].transform(
            lambda s: rolling_max(s, breakout_lookback).shift(1)
        )
        panel["breakout"] = panel["close"] > rolling_high

    if strategy_name == "momentum_breakout" or {
        "use_52w_high",
        "use_mom_12_1",
    }.intersection(ranking_cfg.keys()):
        panel["mom_12_1"] = by_code["close"].transform(
            lambda s: ret(s, 252) - ret(s, 21)
        )
        panel["nh_52w"] = by_code["close"].transform(lambda s: s / rolling_max(s, 252))

    panel["vol20"] = by_code["vol"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    panel["vol_ratio"] = panel["vol"] / panel["vol20"]
    panel["amount_yuan"] = panel["amount"] * 1000.0
    panel["avg_amount_20"] = by_code["amount_yuan"].transform(
        lambda s: s.rolling(20, min_periods=20).mean()
    )

    if ranking_cfg.get("use_low_vol", False):
        low_vol_days = int(ranking_cfg.get("low_vol_days", 60))
        panel["volatility"] = by_code["close"].transform(
            lambda s: rolling_vol(s, low_vol_days)
        )

    if strategy_name == "mean_reversion_rebound":
        panel["ret_5"] = by_code["close"].transform(lambda s: ret(s, 5))
        panel["ret_20"] = by_code["close"].transform(lambda s: ret(s, 20))
        panel["rsi_14"] = by_code["close"].transform(lambda s: rsi(s, 14))
        panel["low_20"] = by_code["low"].transform(lambda s: rolling_min(s, 20))
        if mean_revert_ma_days > 0:
            panel["ma_revert"] = by_code["close"].transform(
                lambda s: sma(s, mean_revert_ma_days)
            )

    return panel


def precompute_index_features(index_panel: pd.DataFrame, cfg: Dict) -> pd.DataFrame:
    if index_panel.empty:
        return index_panel
    regime_cfg = cfg.get("strategy", {}).get("regime_filter", {})
    if not regime_cfg.get("enabled", False):
        return index_panel
    ma_days = int(regime_cfg.get("ma_days", 0))
    by_code = index_panel.groupby(level="ts_code", group_keys=False)
    if ma_days > 0:
        index_panel["ma_regime"] = by_code["close"].transform(lambda s: sma(s, ma_days))
    mom_days = int(regime_cfg.get("momentum_days", 0))
    if mom_days > 0:
        index_panel["mom_regime"] = by_code["close"].transform(
            lambda s: ret(s, mom_days)
        )
    return index_panel
