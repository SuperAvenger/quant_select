from __future__ import annotations

from typing import Dict, List, Tuple

import pandas as pd

from quant_a.broker.costs import calc_fee
from quant_a.broker.models import Fill, Order, Position

class Matcher:
    def __init__(self, cfg: Dict) -> None:
        self.cfg = cfg

    def _value_by_prefix(self, ts_code: str, prefix_map: Dict, default: float) -> float:
        if isinstance(prefix_map, dict):
            for prefix, val in prefix_map.items():
                if ts_code.startswith(str(prefix)):
                    try:
                        return float(val)
                    except (TypeError, ValueError):
                        return default
        return default

    def _limit_reject(self, row: pd.Series, side: str) -> bool:
        limit_cfg = self.cfg.get("limit_rule", {})
        if not limit_cfg.get("enabled", False):
            return False
        mode = limit_cfg.get("mode", "conservative")
        open_p = row.get("open")
        high = row.get("high")
        low = row.get("low")
        up_limit = row.get("up_limit")
        down_limit = row.get("down_limit")
        if pd.isna(open_p) or pd.isna(up_limit) or pd.isna(down_limit):
            return False
        if mode == "conservative":
            if side == "BUY" and open_p >= up_limit:
                return True
            if side == "SELL" and open_p <= down_limit:
                return True
        else:
            if side == "BUY" and open_p == high == low == up_limit:
                return True
            if side == "SELL" and open_p == high == low == down_limit:
                return True
        return False

    def match(
        self,
        orders: List[Order],
        exec_date: str,
        panel: pd.DataFrame,
        positions: Dict[str, Position],
        cash: float,
    ) -> Tuple[List[Fill], Dict[str, Position], float]:
        fills: List[Fill] = []
        if panel.empty:
            for order in orders:
                fills.append(
                    Fill(
                        ts_code=order.ts_code,
                        side=order.side,
                        qty=0,
                        price=0.0,
                        exec_date=exec_date,
                        fee=0.0,
                        status="rejected",
                        reason="no_data",
                    )
                )
            return fills, positions, cash

        for order in orders:
            try:
                row = panel.loc[(exec_date, order.ts_code)]
            except KeyError:
                fills.append(
                    Fill(
                        ts_code=order.ts_code,
                        side=order.side,
                        qty=0,
                        price=0.0,
                        exec_date=exec_date,
                        fee=0.0,
                        status="rejected",
                        reason="no_data",
                    )
                )
                continue

            if row.get("suspend", 0) == 1:
                fills.append(
                    Fill(
                        ts_code=order.ts_code,
                        side=order.side,
                        qty=0,
                        price=0.0,
                        exec_date=exec_date,
                        fee=0.0,
                        status="rejected",
                        reason="suspended",
                    )
                )
                continue

            if self._limit_reject(row, order.side):
                fills.append(
                    Fill(
                        ts_code=order.ts_code,
                        side=order.side,
                        qty=0,
                        price=0.0,
                        exec_date=exec_date,
                        fee=0.0,
                        status="rejected",
                        reason="limit",
                    )
                )
                continue

            if self.cfg.get("t_plus_one", False) and order.side == "SELL":
                pos = positions.get(order.ts_code)
                if pos and pos.last_buy_date == exec_date:
                    fills.append(
                        Fill(
                            ts_code=order.ts_code,
                            side=order.side,
                            qty=0,
                            price=0.0,
                            exec_date=exec_date,
                            fee=0.0,
                            status="rejected",
                            reason="t_plus_one",
                        )
                    )
                    continue

            open_p = row.get("open")
            if pd.isna(open_p) or open_p <= 0:
                fills.append(
                    Fill(
                        ts_code=order.ts_code,
                        side=order.side,
                        qty=0,
                        price=0.0,
                        exec_date=exec_date,
                        fee=0.0,
                        status="rejected",
                        reason="bad_price",
                    )
                )
                continue

            slippage_bps = float(self.cfg.get("slippage_bps", 0.0))
            if order.side == "BUY":
                fill_price = open_p * (1.0 + slippage_bps / 10000.0)
            else:
                fill_price = open_p * (1.0 - slippage_bps / 10000.0)

            notional = fill_price * order.qty
            commission_bps = self._value_by_prefix(
                order.ts_code,
                self.cfg.get("commission_bps_by_prefix", {}) or {},
                float(self.cfg.get("commission_bps", 0.0)),
            )
            stamp_tax_bps = self._value_by_prefix(
                order.ts_code,
                self.cfg.get("stamp_tax_bps_by_prefix", {}) or {},
                float(self.cfg.get("stamp_tax_bps", 0.0)),
            )
            min_commission = float(self.cfg.get("min_commission", 0.0))
            fee = calc_fee(
                notional,
                order.side,
                commission_bps,
                stamp_tax_bps,
                min_commission,
            )

            if order.side == "BUY" and cash < notional + fee:
                fills.append(
                    Fill(
                        ts_code=order.ts_code,
                        side=order.side,
                        qty=0,
                        price=0.0,
                        exec_date=exec_date,
                        fee=0.0,
                        status="rejected",
                        reason="no_cash",
                    )
                )
                continue

            if order.side == "SELL":
                pos = positions.get(order.ts_code)
                if not pos or pos.qty < order.qty:
                    fills.append(
                        Fill(
                            ts_code=order.ts_code,
                            side=order.side,
                            qty=0,
                            price=0.0,
                            exec_date=exec_date,
                            fee=0.0,
                            status="rejected",
                            reason="no_position",
                        )
                    )
                    continue

            cash = cash - notional - fee if order.side == "BUY" else cash + notional - fee

            if order.side == "BUY":
                pos = positions.get(order.ts_code)
                if pos:
                    total_cost = pos.avg_cost * pos.qty + fill_price * order.qty
                    total_qty = pos.qty + order.qty
                    pos.avg_cost = total_cost / total_qty
                    pos.qty = total_qty
                    pos.last_buy_date = exec_date
                    pos.highest_close_since_entry = max(
                        pos.highest_close_since_entry, row.get("close", fill_price)
                    )
                else:
                    positions[order.ts_code] = Position(
                        qty=order.qty,
                        avg_cost=fill_price,
                        last_buy_date=exec_date,
                        highest_close_since_entry=row.get("close", fill_price),
                    )
            else:
                pos = positions.get(order.ts_code)
                if pos:
                    pos.qty -= order.qty
                    if pos.qty <= 0:
                        positions.pop(order.ts_code, None)

            fills.append(
                Fill(
                    ts_code=order.ts_code,
                    side=order.side,
                    qty=order.qty,
                    price=fill_price,
                    exec_date=exec_date,
                    fee=fee,
                    status="filled",
                    reason=order.reason,
                )
            )

        return fills, positions, cash
