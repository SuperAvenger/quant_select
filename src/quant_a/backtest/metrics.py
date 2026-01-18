from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


def _compute_trade_stats(trades_df: pd.DataFrame) -> Tuple[float, float, float]:
    if trades_df.empty:
        return 0.0, 0.0, 0.0
    trades = trades_df[trades_df["status"] == "filled"].copy()
    if trades.empty:
        return 0.0, 0.0, 0.0
    trades["exec_date"] = pd.to_datetime(trades["exec_date"])
    trades = trades.sort_values("exec_date")

    lots: Dict[str, List[Dict[str, object]]] = {}
    pnl_list: List[float] = []
    holding_days: List[int] = []
    for _, row in trades.iterrows():
        ts_code = row["ts_code"]
        side = row["side"]
        qty = int(row["qty"])
        price = float(row["price"])
        fee = float(row["fee"])
        exec_date = row["exec_date"]

        if side == "BUY":
            lots.setdefault(ts_code, []).append(
                {"qty": qty, "price": price, "fee": fee, "date": exec_date}
            )
            continue

        if side != "SELL":
            continue

        remaining = qty
        while remaining > 0 and lots.get(ts_code):
            lot = lots[ts_code][0]
            lot_qty = int(lot["qty"])
            take = min(lot_qty, remaining)
            buy_fee = float(lot["fee"]) * (take / lot_qty) if lot_qty else 0.0
            sell_fee = fee * (take / qty) if qty else 0.0
            buy_cost = take * float(lot["price"]) + buy_fee
            sell_proceeds = take * price - sell_fee
            pnl_list.append(sell_proceeds - buy_cost)
            holding_days.append(int((exec_date - lot["date"]).days))
            remaining -= take
            lot["qty"] = lot_qty - take
            if lot["qty"] <= 0:
                lots[ts_code].pop(0)

    win_rate = float(np.mean([p > 0 for p in pnl_list])) if pnl_list else 0.0
    avg_holding_days = float(np.mean(holding_days)) if holding_days else 0.0
    trade_count = float(len(pnl_list))
    return win_rate, avg_holding_days, trade_count


def compute_metrics(equity_df: pd.DataFrame, trades_df: pd.DataFrame) -> Dict:
    if equity_df.empty:
        return {}
    equity = equity_df["equity"].astype(float)
    returns = equity.pct_change().fillna(0.0)
    total_return = equity.iloc[-1] / equity.iloc[0] - 1.0
    if len(equity) > 1:
        ann_return = (1.0 + total_return) ** (252.0 / (len(equity) - 1)) - 1.0
    else:
        ann_return = 0.0
    ann_vol = returns.std(ddof=0) * np.sqrt(252.0)
    sharpe = 0.0
    if returns.std(ddof=0) > 0:
        sharpe = returns.mean() / returns.std(ddof=0) * np.sqrt(252.0)
    downside = returns[returns < 0]
    sortino = 0.0
    if len(downside) > 0 and downside.std(ddof=0) > 0:
        sortino = returns.mean() / downside.std(ddof=0) * np.sqrt(252.0)

    cum_max = equity.cummax()
    drawdown = equity / cum_max - 1.0
    max_drawdown = drawdown.min()

    n_trades = 0
    if not trades_df.empty:
        n_trades = int((trades_df["status"] == "filled").sum())

    win_rate, avg_holding_days, closed_trades = _compute_trade_stats(trades_df)
    turnover = 0.0
    if not trades_df.empty and not equity_df.empty:
        notional = (trades_df["price"].abs() * trades_df["qty"].abs()).sum()
        avg_equity = equity.mean()
        if avg_equity > 0:
            turnover = float(notional / avg_equity / 2.0)

    return {
        "total_return": float(total_return),
        "annualized_return": float(ann_return),
        "annualized_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "max_drawdown": float(max_drawdown),
        "trade_count": n_trades,
        "win_rate": float(win_rate),
        "avg_holding_days": float(avg_holding_days),
        "closed_trades": int(closed_trades),
        "turnover": float(turnover),
    }
