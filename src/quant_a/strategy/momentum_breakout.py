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


@register_strategy("momentum_breakout")
class MomentumBreakoutStrategy(BaseStrategy):
    def __init__(self, cfg: Dict, dates: List[str], index_panel: pd.DataFrame) -> None:
        self.cfg = cfg
        self.rebalance_dates = compute_rebalance_dates(dates, cfg["strategy"]["rebalance"])
        self.index_panel = index_panel

    def _allow_new_positions(self, signal_date: str) -> bool:
        regime_cfg = self.cfg["strategy"]["regime_filter"]
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
        min_amount = universe_cfg.get("min_avg_amount_20")
        data = date_slice.copy()

        data = data[data["close"] > data["ma_trend"]]
        data = data[data["breakout"] == True]
        data = data[data["vol_ratio"] >= float(entry_cfg["volume_ratio_min"])]
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
        if ranking_cfg.get("use_52w_high", True):
            score += float(ranking_cfg["w_52w_high"]) * _zscore(candidates["nh_52w"])
        if ranking_cfg.get("use_mom_12_1", True):
            score += float(ranking_cfg["w_mom_12_1"]) * _zscore(candidates["mom_12_1"])
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

        exit_names: Set[str] = set()
        for ts_code, pos in positions.items():
            if date_slice.empty or ts_code not in date_slice.index:
                continue
            row = date_slice.loc[ts_code]
            reasons = []
            if exit_cfg.get("use_ma_stop", False) and row["close"] < row["ma_stop"]:
                reasons.append("ma_stop")
            if exit_cfg.get("use_atr_trailing", False):
                atr_k = float(exit_cfg["atr_k"])
                stop_level = pos.highest_close_since_entry - atr_k * row["atr"]
                if row["close"] < stop_level:
                    reasons.append("atr_trailing")
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
