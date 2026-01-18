from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set

import numpy as np
import pandas as pd

from quant_a.broker.models import Order, Position
from quant_a.strategy.base import (
    BaseStrategy,
    SignalContext,
    compute_rebalance_dates,
    register_strategy,
)


def _zscore(series: pd.Series) -> pd.Series:
    mean = series.mean()
    std = series.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=series.index)
    return (series - mean) / std


def _date_slice(panel: pd.DataFrame, date: str) -> pd.DataFrame:
    try:
        return panel.xs(date, level="trade_date")
    except KeyError:
        return pd.DataFrame()


def _lot_size_for(ts_code: str, exec_cfg: Dict) -> int:
    lot_size = int(exec_cfg.get("lot_size", 100))
    prefix_map = exec_cfg.get("lot_size_by_prefix", {}) or {}
    if isinstance(prefix_map, dict):
        for prefix, size in prefix_map.items():
            if ts_code.startswith(str(prefix)):
                try:
                    lot_size = int(size)
                except (TypeError, ValueError):
                    pass
                break
    return max(lot_size, 1)


@register_strategy("mean_reversion_rebound")
class MeanReversionReboundStrategy(BaseStrategy):
    def __init__(self, cfg: Dict, dates: List[str], index_panel: pd.DataFrame) -> None:
        self.cfg = cfg
        self.rebalance_dates = compute_rebalance_dates(dates, cfg["strategy"]["rebalance"])
        self.index_panel = index_panel

    def _allow_new_positions(self, signal_date: str) -> bool:
        regime_cfg = self.cfg.get("strategy", {}).get("regime_filter", {})
        if not regime_cfg.get("enabled", False):
            return True
        index_code = regime_cfg.get("index_ts_code")
        if not index_code or self.index_panel.empty:
            return False
        try:
            row = self.index_panel.loc[(signal_date, index_code)]
        except KeyError:
            return False
        if not bool(row["close"] > row["ma_regime"]):
            return False
        mom_days = int(regime_cfg.get("momentum_days", 0))
        if mom_days > 0:
            mom_min = float(regime_cfg.get("momentum_min", 0.0))
            mom_val = row.get("mom_regime")
            if pd.isna(mom_val) or float(mom_val) < mom_min:
                return False
        return True

    def _candidate_selection(self, date_slice: pd.DataFrame) -> pd.DataFrame:
        entry_cfg = self.cfg["strategy"]["entry"]
        universe_cfg = self.cfg.get("universe", {})
        data = date_slice.copy()

        ret_5_max = entry_cfg.get("ret_5_max")
        if ret_5_max is not None:
            data = data[data["ret_5"] <= float(ret_5_max)]
        ret_20_max = entry_cfg.get("ret_20_max")
        if ret_20_max is not None:
            data = data[data["ret_20"] <= float(ret_20_max)]
        rsi_max = entry_cfg.get("rsi_max")
        if rsi_max is not None:
            data = data[data["rsi_14"] <= float(rsi_max)]
        rebound_lookback = float(entry_cfg.get("rebound_lookback", 0.0))
        if rebound_lookback > 0:
            data = data[data["close"] <= data["low_20"] * (1.0 + rebound_lookback)]

        min_amount = universe_cfg.get("min_avg_amount_20")
        if min_amount:
            data = data[data["avg_amount_20"] >= float(min_amount)]
        if universe_cfg.get("exclude_suspended", False) and "suspend" in data.columns:
            data = data[data["suspend"] == 0]
        return data

    def _rank_targets(self, candidates: pd.DataFrame) -> List[str]:
        if candidates.empty:
            return []
        ranking_cfg = self.cfg["strategy"]["ranking"]
        score = 0.0
        if ranking_cfg.get("use_ret_5", True):
            score += float(ranking_cfg["w_ret_5"]) * _zscore(-candidates["ret_5"])
        if ranking_cfg.get("use_ret_20", True):
            score += float(ranking_cfg["w_ret_20"]) * _zscore(-candidates["ret_20"])
        if ranking_cfg.get("use_low_vol", False):
            score += float(ranking_cfg["w_low_vol"]) * _zscore(-candidates["volatility"])
        ranked = candidates.assign(score=score).sort_values("score", ascending=False)
        top_n = int(self.cfg["strategy"]["top_n"])
        return ranked.head(top_n).index.tolist()

    def get_rebalance_snapshot(
        self, panel: pd.DataFrame, signal_date: str
    ) -> Optional[Dict[str, object]]:
        if signal_date not in self.rebalance_dates:
            return None
        date_slice = _date_slice(panel, signal_date)
        allow_new = self._allow_new_positions(signal_date)
        candidate_count = 0
        selected: List[str] = []
        if allow_new and not date_slice.empty:
            candidates = self._candidate_selection(date_slice)
            candidate_count = int(len(candidates))
            selected = self._rank_targets(candidates)
        return {
            "signal_date": signal_date,
            "allow_new": allow_new,
            "candidate_count": candidate_count,
            "selected_count": int(len(selected)),
            "top_names": ";".join(selected),
        }

    def generate_orders(
        self,
        panel: pd.DataFrame,
        positions: Dict[str, Position],
        ctx: SignalContext,
    ) -> List[Order]:
        orders: List[Order] = []
        exit_cfg = self.cfg["strategy"]["exit"]
        risk_cfg = self.cfg["risk"]
        exec_cfg = self.cfg["execution"]

        date_slice = _date_slice(panel, ctx.signal_date)

        mean_revert_ma_days = int(exit_cfg.get("mean_revert_ma_days", 0))
        take_profit_pct = float(exit_cfg.get("take_profit_pct", 0.0))
        stop_loss_pct = float(exit_cfg.get("stop_loss_pct", 0.0))
        max_hold_days = int(exit_cfg.get("max_hold_days", 0))

        exit_names: Set[str] = set()
        for ts_code, pos in positions.items():
            if date_slice.empty or ts_code not in date_slice.index:
                continue
            row = date_slice.loc[ts_code]
            close_price = row.get("close")
            if pd.isna(close_price):
                continue
            reasons = []
            ma_revert = row.get("ma_revert")
            if mean_revert_ma_days > 0 and pd.notna(ma_revert):
                if close_price >= ma_revert:
                    reasons.append("mean_revert")
            entry_price = pos.avg_cost if pos.avg_cost > 0 else float(close_price)
            if take_profit_pct > 0 and close_price >= entry_price * (1.0 + take_profit_pct):
                reasons.append("take_profit")
            if stop_loss_pct > 0 and close_price <= entry_price * (1.0 - stop_loss_pct):
                reasons.append("stop_loss")
            if max_hold_days > 0 and pos.last_buy_date:
                try:
                    hold_days = (
                        pd.to_datetime(ctx.signal_date)
                        - pd.to_datetime(pos.last_buy_date)
                    ).days
                except (TypeError, ValueError):
                    hold_days = None
                if hold_days is not None and hold_days >= max_hold_days:
                    reasons.append("max_hold")
            if reasons:
                exit_names.add(ts_code)
                orders.append(
                    Order(
                        ts_code=ts_code,
                        side="SELL",
                        qty=pos.qty,
                        signal_date=ctx.signal_date,
                        exec_date=ctx.exec_date,
                        reason="exit:" + ",".join(reasons),
                    )
                )

        if ctx.signal_date not in self.rebalance_dates:
            return orders

        allow_new = self._allow_new_positions(ctx.signal_date)
        if date_slice.empty:
            return orders
        if not allow_new:
            return orders

        candidates = self._candidate_selection(date_slice)
        target_names = self._rank_targets(candidates)

        max_weight = float(risk_cfg["max_weight_per_name"])
        target_weights: Dict[str, float] = {}
        if target_names:
            equal_w = 1.0 / len(target_names)
            for name in target_names:
                target_weights[name] = min(equal_w, max_weight)

        for name in exit_names:
            target_weights[name] = 0.0

        portfolio_value = ctx.cash
        for ts_code, pos in positions.items():
            price = ctx.last_prices.get(ts_code, pos.avg_cost)
            portfolio_value += pos.qty * price
        if portfolio_value <= 0:
            return orders

        current_weights: Dict[str, float] = {}
        for ts_code, pos in positions.items():
            price = ctx.last_prices.get(ts_code, pos.avg_cost)
            current_weights[ts_code] = (pos.qty * price) / portfolio_value

        union_names = set(current_weights) | set(target_weights)
        turnover = 0.0
        for name in union_names:
            turnover += abs(target_weights.get(name, 0.0) - current_weights.get(name, 0.0))
        turnover *= 0.5

        max_turnover = float(exec_cfg["max_turnover"])
        if turnover > max_turnover and turnover > 0:
            alpha = max_turnover / turnover
            scaled_targets: Dict[str, float] = {}
            for name in union_names:
                cur = current_weights.get(name, 0.0)
                tgt = target_weights.get(name, 0.0)
                scaled_targets[name] = cur + alpha * (tgt - cur)
            target_weights = scaled_targets

        min_trade_value = 0
        for ts_code in union_names:
            if ts_code in exit_names:
                continue
            if date_slice.empty or ts_code not in date_slice.index:
                continue
            price = date_slice.loc[ts_code, "close"]
            if pd.isna(price) or price <= 0:
                continue
            lot = _lot_size_for(ts_code, exec_cfg)
            tgt_value = target_weights.get(ts_code, 0.0) * portfolio_value
            cur_value = current_weights.get(ts_code, 0.0) * portfolio_value
            diff_value = tgt_value - cur_value
            if abs(diff_value) <= min_trade_value:
                continue
            if diff_value < 0:
                qty = int(abs(diff_value) / price / lot) * lot
                if qty <= 0:
                    continue
                qty = min(qty, positions.get(ts_code, Position(0, 0.0, "", 0.0)).qty)
                if qty > 0:
                    orders.append(
                        Order(
                            ts_code=ts_code,
                            side="SELL",
                            qty=qty,
                            signal_date=ctx.signal_date,
                            exec_date=ctx.exec_date,
                            reason="rebalance",
                        )
                    )
            else:
                qty = int(diff_value / price / lot) * lot
                if qty <= 0:
                    continue
                orders.append(
                    Order(
                        ts_code=ts_code,
                        side="BUY",
                        qty=qty,
                        signal_date=ctx.signal_date,
                        exec_date=ctx.exec_date,
                        reason="rebalance",
                    )
                )

        orders.sort(key=lambda o: 0 if o.side == "SELL" else 1)
        return orders
