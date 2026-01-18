#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import itertools
import json
import os
import sys
from typing import Dict, Iterable

import pandas as pd

from quant_a.backtest.engine import run_backtest
from quant_a.backtest.metrics import compute_metrics
from quant_a.config.loader import load_config
from quant_a.data.panel_builder import build_panel
from quant_a.data.tushare_client import TuShareClient
from quant_a.features.precompute import precompute_features, precompute_index_features


def _param_grid() -> Iterable[Dict[str, float]]:
    breakout_lookbacks = [60, 90, 120]
    trend_ma_days = [60, 90]
    volume_ratio_min = [1.2, 1.5]
    for breakout, trend, vol_ratio in itertools.product(
        breakout_lookbacks, trend_ma_days, volume_ratio_min
    ):
        yield {
            "breakout_lookback": breakout,
            "trend_ma_days": trend,
            "volume_ratio_min": vol_ratio,
        }


def _score(metrics: Dict[str, float]) -> float:
    sharpe = float(metrics.get("sharpe", 0.0))
    ann = float(metrics.get("annualized_return", 0.0))
    max_dd = abs(float(metrics.get("max_drawdown", 0.0)))
    return sharpe + ann - 0.5 * max_dd


def main() -> None:
    parser = argparse.ArgumentParser(description="Momentum breakout parameter search")
    parser.add_argument("--config", required=True, help="Base config YAML")
    parser.add_argument("--out", default="outputs/param_search", help="Output dir")
    parser.add_argument("--start", default=None, help="Override backtest start YYYYMMDD")
    parser.add_argument("--end", default=None, help="Override backtest end YYYYMMDD")
    parser.add_argument("--max-runs", type=int, default=None, help="Optional cap")
    parser.add_argument(
        "--max-names",
        type=int,
        default=None,
        help="Optional universe cap for faster searches",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.start:
        cfg["backtest"]["start"] = str(args.start)
    if args.end:
        cfg["backtest"]["end"] = str(args.end)
    cfg["backtest"]["resume"] = False
    if args.max_names:
        cfg.setdefault("universe", {})["max_names"] = int(args.max_names)

    os.makedirs(args.out, exist_ok=True)

    client = TuShareClient(
        token=cfg["tushare"]["token"], timeout=int(cfg["tushare"].get("timeout", 30))
    )
    panel, dates, index_panel = build_panel(client, cfg)
    if panel.empty:
        raise RuntimeError("Empty panel; check cache or data pull settings.")

    results = []
    for idx, params in enumerate(_param_grid(), start=1):
        if args.max_runs is not None and idx > args.max_runs:
            break
        run_cfg = copy.deepcopy(cfg)
        entry_cfg = run_cfg["strategy"]["entry"]
        entry_cfg["breakout_lookback"] = int(params["breakout_lookback"])
        entry_cfg["trend_ma_days"] = int(params["trend_ma_days"])
        entry_cfg["volume_ratio_min"] = float(params["volume_ratio_min"])

        panel = precompute_features(panel, run_cfg)
        index_panel = precompute_index_features(index_panel, run_cfg)

        equity_df, trades_df, _ = run_backtest(panel, dates, index_panel, run_cfg)
        metrics = compute_metrics(equity_df, trades_df)
        metrics["score"] = _score(metrics)

        record = {**params, **metrics}
        results.append(record)

        print(
            f"[{idx}] breakout={params['breakout_lookback']} trend={params['trend_ma_days']}"
            f" vol_ratio={params['volume_ratio_min']} sharpe={metrics.get('sharpe', 0.0):.2f}"
            f" ann={metrics.get('annualized_return', 0.0):.2%}"
            f" max_dd={metrics.get('max_drawdown', 0.0):.2%}"
            f" score={metrics['score']:.3f}"
        )

    if not results:
        raise RuntimeError("No results generated.")

    df = pd.DataFrame(results).sort_values("score", ascending=False)
    df.to_csv(os.path.join(args.out, "results.csv"), index=False)

    best = df.iloc[0].to_dict() if not df.empty else {}
    with open(os.path.join(args.out, "best.json"), "w", encoding="utf-8") as f:
        json.dump(best, f, ensure_ascii=True, indent=2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
