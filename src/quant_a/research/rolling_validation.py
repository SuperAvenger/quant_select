from __future__ import annotations

import math
from typing import Any, Dict

import pandas as pd


def build_rolling_validation(
    equity_df: pd.DataFrame,
    window_days: int = 60,
    step_days: int = 20,
) -> Dict[str, Any]:
    """Measure strategy stability over overlapping windows of the equity curve."""
    if window_days < 2 or step_days < 1:
        raise ValueError("window_days must be >= 2 and step_days must be >= 1")
    if equity_df.empty or len(equity_df) < window_days:
        return {
            "window_days": window_days,
            "step_days": step_days,
            "windows": [],
            "summary": {"window_count": 0, "positive_window_rate": None},
        }

    data = equity_df[["date", "equity"]].copy()
    data["date"] = pd.to_datetime(data["date"])
    data["equity"] = pd.to_numeric(data["equity"], errors="raise")
    if not data["equity"].map(math.isfinite).all() or (data["equity"] <= 0).any():
        raise ValueError("equity values must be finite and greater than zero")
    data = data.sort_values("date").reset_index(drop=True)

    starts = list(range(0, len(data) - window_days + 1, step_days))
    final_start = len(data) - window_days
    if starts[-1] != final_start:
        starts.append(final_start)

    windows = []
    for start in starts:
        frame = data.iloc[start : start + window_days]
        equity = frame["equity"]
        returns = equity.pct_change().dropna()
        drawdown = equity / equity.cummax() - 1.0
        total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
        volatility = float(returns.std(ddof=0) * math.sqrt(252)) if len(returns) else 0.0
        windows.append(
            {
                "start": frame["date"].iloc[0].strftime("%Y-%m-%d"),
                "end": frame["date"].iloc[-1].strftime("%Y-%m-%d"),
                "observations": int(len(frame)),
                "total_return": total_return,
                "max_drawdown": float(drawdown.min()),
                "annualized_volatility": volatility,
            }
        )

    returns = pd.Series([window["total_return"] for window in windows], dtype=float)
    drawdowns = pd.Series([window["max_drawdown"] for window in windows], dtype=float)
    return {
        "window_days": window_days,
        "step_days": step_days,
        "windows": windows,
        "summary": {
            "window_count": len(windows),
            "positive_window_rate": float((returns > 0).mean()),
            "median_window_return": float(returns.median()),
            "worst_window_return": float(returns.min()),
            "worst_window_drawdown": float(drawdowns.min()),
        },
        "interpretation": "Overlapping-window stability diagnostic; not a retrained out-of-sample backtest.",
    }
