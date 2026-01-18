from __future__ import annotations

import os
from typing import Dict, List
import pandas as pd

from quant_a.strategy.mean_reversion_rebound import MeanReversionReboundStrategy
from quant_a.strategy.momentum_breakout import MomentumBreakoutStrategy


def summarize_trades(trades_df: pd.DataFrame) -> Dict:
    if trades_df.empty:
        return {
            "total_orders": 0,
            "filled": 0,
            "rejected": 0,
            "fill_rate": 0.0,
            "by_status": {},
            "rejected_reasons": {},
            "filled_reasons": {},
        }
    total_orders = int(len(trades_df))
    by_status = trades_df["status"].value_counts().to_dict()
    filled = int(by_status.get("filled", 0))
    rejected = int(by_status.get("rejected", 0))
    fill_rate = filled / total_orders if total_orders > 0 else 0.0

    rejected_reasons = {}
    filled_reasons = {}
    if "reason" in trades_df.columns:
        rejected_reasons = (
            trades_df[trades_df["status"] == "rejected"]["reason"]
            .value_counts()
            .to_dict()
        )
        filled_reasons = (
            trades_df[trades_df["status"] == "filled"]["reason"]
            .value_counts()
            .to_dict()
        )
    for reason in [
        "no_data",
        "suspended",
        "limit",
        "t_plus_one",
        "bad_price",
        "no_cash",
        "no_position",
    ]:
        rejected_reasons.setdefault(reason, 0)

    return {
        "total_orders": total_orders,
        "filled": filled,
        "rejected": rejected,
        "fill_rate": float(fill_rate),
        "by_status": by_status,
        "rejected_reasons": rejected_reasons,
        "filled_reasons": filled_reasons,
    }


def build_rebalance_stats(
    panel: pd.DataFrame, dates: List[str], index_panel: pd.DataFrame, cfg: Dict
) -> pd.DataFrame:
    strategy_name = str(cfg.get("strategy", {}).get("name", "momentum_breakout"))
    if strategy_name == "momentum_breakout":
        strategy = MomentumBreakoutStrategy(cfg, dates, index_panel)
    elif strategy_name == "mean_reversion_rebound":
        strategy = MeanReversionReboundStrategy(cfg, dates, index_panel)
    else:
        return pd.DataFrame()
    rows: List[Dict[str, object]] = []
    for date in dates:
        snap = strategy.get_rebalance_snapshot(panel, date)
        if snap is not None:
            rows.append(snap)
    return pd.DataFrame(rows)


def build_closed_trades(trades_df: pd.DataFrame) -> pd.DataFrame:
    if trades_df.empty:
        return pd.DataFrame()
    trades = trades_df[trades_df["status"] == "filled"].copy()
    if trades.empty:
        return pd.DataFrame()
    trades["exec_date"] = pd.to_datetime(trades["exec_date"])
    trades = trades.sort_values("exec_date")

    lots: Dict[str, List[Dict[str, object]]] = {}
    records: List[Dict[str, object]] = []
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
            entry_price = float(lot["price"])
            exit_price = price
            buy_cost = take * entry_price + buy_fee
            sell_proceeds = take * exit_price - sell_fee
            pnl = sell_proceeds - buy_cost
            hold_days = int((exec_date - lot["date"]).days)
            records.append(
                {
                    "ts_code": ts_code,
                    "entry_date": lot["date"].strftime("%Y%m%d"),
                    "exit_date": exec_date.strftime("%Y%m%d"),
                    "qty": take,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl": pnl,
                    "return": pnl / buy_cost if buy_cost else 0.0,
                    "holding_days": hold_days,
                }
            )
            remaining -= take
            lot["qty"] = lot_qty - take
            if lot["qty"] <= 0:
                lots[ts_code].pop(0)

    return pd.DataFrame(records)


def build_yearly_stats(equity_df: pd.DataFrame) -> pd.DataFrame:
    if equity_df.empty:
        return pd.DataFrame()
    data = equity_df.copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.sort_values("date")
    data["year"] = data["date"].dt.year
    rows: List[Dict[str, object]] = []
    for year, group in data.groupby("year"):
        if group.empty:
            continue
        start_equity = float(group["equity"].iloc[0])
        end_equity = float(group["equity"].iloc[-1])
        total_return = end_equity / start_equity - 1.0 if start_equity else 0.0
        equity = group["equity"].astype(float)
        cum_max = equity.cummax()
        drawdown = equity / cum_max - 1.0
        max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0
        rows.append(
            {
                "year": int(year),
                "total_return": float(total_return),
                "max_drawdown": max_drawdown,
            }
        )
    return pd.DataFrame(rows)


def build_monthly_win_rate(closed_trades: pd.DataFrame) -> pd.DataFrame:
    if closed_trades.empty:
        return pd.DataFrame()
    data = closed_trades.copy()
    data["exit_date"] = pd.to_datetime(data["exit_date"])
    data["month"] = data["exit_date"].dt.to_period("M").astype(str)
    grouped = data.groupby("month")
    rows: List[Dict[str, object]] = []
    for month, group in grouped:
        pnl = group["pnl"]
        win_rate = float((pnl > 0).mean()) if len(pnl) else 0.0
        rows.append(
            {"month": month, "closed_trades": int(len(group)), "win_rate": win_rate}
        )
    return pd.DataFrame(rows)


def build_industry_win_rate(
    closed_trades: pd.DataFrame, industry_map: Dict[str, str]
) -> pd.DataFrame:
    if closed_trades.empty or not industry_map:
        return pd.DataFrame()
    data = closed_trades.copy()
    data["industry"] = data["ts_code"].map(industry_map).fillna("unknown")
    grouped = data.groupby("industry")
    rows: List[Dict[str, object]] = []
    for industry, group in grouped:
        pnl = group["pnl"]
        win_rate = float((pnl > 0).mean()) if len(pnl) else 0.0
        rows.append(
            {
                "industry": industry,
                "closed_trades": int(len(group)),
                "win_rate": win_rate,
            }
        )
    return pd.DataFrame(rows)


def plot_equity_drawdown(equity_df: pd.DataFrame, out_dir: str) -> List[str]:
    if equity_df.empty:
        return []
    try:
        if "MPLCONFIGDIR" not in os.environ:
            mpl_dir = os.path.join(out_dir, ".mplconfig")
            os.makedirs(mpl_dir, exist_ok=True)
            os.environ["MPLCONFIGDIR"] = mpl_dir
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return []

    paths: List[str] = []
    equity = equity_df["equity"].astype(float)
    dates = pd.to_datetime(equity_df["date"])

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(dates, equity, color="#1f77b4", linewidth=1.2)
    ax.set_title("Equity Curve")
    ax.set_ylabel("Equity")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    equity_path = f"{out_dir}/equity_curve.png"
    fig.tight_layout()
    fig.savefig(equity_path, dpi=150)
    plt.close(fig)
    paths.append(equity_path)

    cum_max = equity.cummax()
    drawdown = equity / cum_max - 1.0
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.fill_between(dates, drawdown, 0.0, color="#d62728", alpha=0.4)
    ax.set_title("Drawdown")
    ax.set_ylabel("Drawdown")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    dd_path = f"{out_dir}/drawdown.png"
    fig.tight_layout()
    fig.savefig(dd_path, dpi=150)
    plt.close(fig)
    paths.append(dd_path)

    return paths
