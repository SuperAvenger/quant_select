from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

from quant_a.broker.matcher import Matcher
from quant_a.broker.models import Fill, Position
from quant_a.strategy import SignalContext, create_strategy


def _date_slice(panel: pd.DataFrame, date: str) -> pd.DataFrame:
    try:
        return panel.xs(date, level="trade_date")
    except KeyError:
        return pd.DataFrame()


def run_backtest(
    panel: pd.DataFrame,
    dates: List[str],
    index_panel: pd.DataFrame,
    cfg: Dict,
    initial_cash: float = 1_000_000.0,
    resume_state: Optional[Dict] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict]:
    strategy_name = str(cfg.get("strategy", {}).get("name", "momentum_breakout"))
    strategy = create_strategy(strategy_name, cfg, dates, index_panel)
    matcher = Matcher(cfg["execution"])

    positions: Dict[str, Position] = {}
    cash = initial_cash
    last_prices: Dict[str, float] = {}

    equity_records: List[Dict] = []
    trades: List[Fill] = []

    if not dates:
        return pd.DataFrame(), pd.DataFrame(), {}

    start_idx = 0
    if resume_state:
        cash = float(resume_state.get("cash", cash))
        last_prices = {
            str(k): float(v) for k, v in resume_state.get("last_prices", {}).items()
        }
        positions = {}
        for ts_code, pdata in resume_state.get("positions", {}).items():
            if not isinstance(pdata, dict):
                continue
            positions[str(ts_code)] = Position(
                qty=int(pdata.get("qty", 0)),
                avg_cost=float(pdata.get("avg_cost", 0.0)),
                last_buy_date=str(pdata.get("last_buy_date", "")),
                highest_close_since_entry=float(
                    pdata.get("highest_close_since_entry", 0.0)
                ),
            )
        last_date = str(resume_state.get("last_date", ""))
        if last_date in dates:
            start_idx = dates.index(last_date)
        elif last_date:
            raise ValueError(f"Resume last_date {last_date} not in backtest dates.")
        equity = float(resume_state.get("equity", 0.0))
        if equity <= 0:
            equity = cash
            for ts_code, pos in positions.items():
                price = last_prices.get(ts_code, pos.avg_cost)
                equity += pos.qty * price
        equity_records.append(
            {"date": dates[start_idx], "equity": equity, "cash": cash, "n_pos": len(positions)}
        )
    else:
        equity_records.append(
            {"date": dates[0], "equity": initial_cash, "cash": initial_cash, "n_pos": 0}
        )

    for i in range(start_idx, len(dates) - 1):
        signal_date = dates[i]
        exec_date = dates[i + 1]

        signal_slice = _date_slice(panel, signal_date)
        if not signal_slice.empty:
            for ts_code, row in signal_slice.iterrows():
                if pd.notna(row.get("close")):
                    last_prices[ts_code] = float(row["close"])

        for ts_code, pos in positions.items():
            price = last_prices.get(ts_code)
            if price is not None:
                pos.highest_close_since_entry = max(pos.highest_close_since_entry, price)

        ctx = SignalContext(
            signal_date=signal_date,
            exec_date=exec_date,
            last_prices=last_prices,
            cash=cash,
        )
        orders = strategy.generate_orders(panel, positions, ctx)
        fills, positions, cash = matcher.match(orders, exec_date, panel, positions, cash)
        trades.extend(fills)

        exec_slice = _date_slice(panel, exec_date)
        if not exec_slice.empty:
            for ts_code, row in exec_slice.iterrows():
                if pd.notna(row.get("close")):
                    last_prices[ts_code] = float(row["close"])

        equity = cash
        for ts_code, pos in positions.items():
            price = last_prices.get(ts_code, pos.avg_cost)
            equity += pos.qty * price

        equity_records.append(
            {"date": exec_date, "equity": equity, "cash": cash, "n_pos": len(positions)}
        )

    equity_df = pd.DataFrame(equity_records)
    trades_df = pd.DataFrame([t.__dict__ for t in trades])
    state = {
        "last_date": dates[-1],
        "cash": float(cash),
        "equity": float(equity_records[-1]["equity"]) if equity_records else float(cash),
        "positions": {k: v.__dict__ for k, v in positions.items()},
        "last_prices": {k: float(v) for k, v in last_prices.items()},
    }
    return equity_df, trades_df, state
