from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

from quant_a.broker.matcher import Matcher
from quant_a.broker.models import Order, Position


def scan_limit_events(panel: pd.DataFrame) -> Dict:
    if panel.empty:
        return {"counts": {}, "rates": {}}
    data = panel.copy()
    if not isinstance(data.index, pd.MultiIndex):
        return {"counts": {}, "rates": {}}

    counts: Dict[str, int] = {}
    total = len(data)
    counts["total_rows"] = int(total)
    counts["suspend_rows"] = int((data.get("suspend", 0) == 1).sum())

    if {"open", "high", "low", "up_limit", "down_limit"}.issubset(data.columns):
        up_open = data["open"] >= data["up_limit"]
        down_open = data["open"] <= data["down_limit"]
        counts["limit_up_open"] = int(up_open.sum())
        counts["limit_down_open"] = int(down_open.sum())
        one_word_up = (
            (data["open"] == data["high"])
            & (data["open"] == data["low"])
            & (data["open"] == data["up_limit"])
        )
        one_word_down = (
            (data["open"] == data["high"])
            & (data["open"] == data["low"])
            & (data["open"] == data["down_limit"])
        )
        counts["one_word_up"] = int(one_word_up.sum())
        counts["one_word_down"] = int(one_word_down.sum())
        counts["conservative_buy_reject"] = counts["limit_up_open"]
        counts["conservative_sell_reject"] = counts["limit_down_open"]
        counts["optimistic_buy_reject"] = counts["one_word_up"]
        counts["optimistic_sell_reject"] = counts["one_word_down"]
    else:
        counts["limit_up_open"] = 0
        counts["limit_down_open"] = 0
        counts["one_word_up"] = 0
        counts["one_word_down"] = 0
        counts["conservative_buy_reject"] = 0
        counts["conservative_sell_reject"] = 0
        counts["optimistic_buy_reject"] = 0
        counts["optimistic_sell_reject"] = 0

    rates: Dict[str, float] = {}
    for key, val in counts.items():
        if key == "total_rows":
            continue
        rates[key] = float(val / total) if total > 0 else 0.0

    return {"counts": counts, "rates": rates}


def _pick_sample(panel: pd.DataFrame, mask: pd.Series) -> Optional[Tuple[str, str]]:
    if panel.empty:
        return None
    if mask.empty or not mask.any():
        return None
    sample = panel[mask].iloc[0]
    trade_date = str(sample.name[0])
    ts_code = str(sample.name[1])
    return trade_date, ts_code


def validate_execution_rules(panel: pd.DataFrame, cfg: Dict) -> Dict:
    if panel.empty:
        return {"samples": {}, "summary": {"total": 0, "by_status": {}, "by_reason": {}}}

    data = panel.copy()
    if not isinstance(data.index, pd.MultiIndex):
        return {"samples": {}, "summary": {"total": 0, "by_status": {}, "by_reason": {}}}

    cols = data.columns
    has_limits = "up_limit" in cols and "down_limit" in cols
    has_suspend = "suspend" in cols

    samples: Dict[str, Dict[str, str]] = {}
    orders: List[Order] = []

    if has_suspend:
        mask = data["suspend"] == 1
        pick = _pick_sample(data, mask)
        if pick:
            trade_date, ts_code = pick
            orders.append(
                Order(
                    ts_code=ts_code,
                    side="BUY",
                    qty=100,
                    signal_date=trade_date,
                    exec_date=trade_date,
                    reason="validation:suspend_buy",
                )
            )
            samples["suspend_buy"] = {"trade_date": trade_date, "ts_code": ts_code}

    if has_limits:
        mask = data["open"] >= data["up_limit"]
        pick = _pick_sample(data, mask)
        if pick:
            trade_date, ts_code = pick
            orders.append(
                Order(
                    ts_code=ts_code,
                    side="BUY",
                    qty=100,
                    signal_date=trade_date,
                    exec_date=trade_date,
                    reason="validation:limit_buy",
                )
            )
            samples["limit_buy"] = {"trade_date": trade_date, "ts_code": ts_code}

        mask = data["open"] <= data["down_limit"]
        pick = _pick_sample(data, mask)
        if pick:
            trade_date, ts_code = pick
            orders.append(
                Order(
                    ts_code=ts_code,
                    side="SELL",
                    qty=100,
                    signal_date=trade_date,
                    exec_date=trade_date,
                    reason="validation:limit_sell",
                )
            )
            samples["limit_sell"] = {"trade_date": trade_date, "ts_code": ts_code}

        mask = (data["open"] == data["high"]) & (data["open"] == data["low"]) & (
            data["open"] == data["up_limit"]
        )
        pick = _pick_sample(data, mask)
        if pick:
            trade_date, ts_code = pick
            orders.append(
                Order(
                    ts_code=ts_code,
                    side="BUY",
                    qty=100,
                    signal_date=trade_date,
                    exec_date=trade_date,
                    reason="validation:one_word_buy",
                )
            )
            samples["one_word_buy"] = {"trade_date": trade_date, "ts_code": ts_code}

        mask = (data["open"] == data["high"]) & (data["open"] == data["low"]) & (
            data["open"] == data["down_limit"]
        )
        pick = _pick_sample(data, mask)
        if pick:
            trade_date, ts_code = pick
            orders.append(
                Order(
                    ts_code=ts_code,
                    side="SELL",
                    qty=100,
                    signal_date=trade_date,
                    exec_date=trade_date,
                    reason="validation:one_word_sell",
                )
            )
            samples["one_word_sell"] = {"trade_date": trade_date, "ts_code": ts_code}

    matcher = Matcher(cfg["execution"])
    fills = []
    for order in orders:
        positions = {}
        if order.side == "SELL":
            positions[order.ts_code] = Position(
                qty=order.qty,
                avg_cost=0.0,
                last_buy_date="19000101",
                highest_close_since_entry=0.0,
            )
        cash = 1e9
        matched, _, _ = matcher.match([order], order.exec_date, panel, positions, cash)
        fills.extend(matched)

    by_status: Dict[str, int] = {}
    by_reason: Dict[str, int] = {}
    for fill in fills:
        by_status[fill.status] = by_status.get(fill.status, 0) + 1
        by_reason[fill.reason] = by_reason.get(fill.reason, 0) + 1

    return {
        "samples": samples,
        "summary": {
            "total": len(fills),
            "by_status": by_status,
            "by_reason": by_reason,
        },
        "limit_scan": scan_limit_events(panel),
    }
