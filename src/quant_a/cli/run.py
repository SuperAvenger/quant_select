from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd

from quant_a.backtest.engine import run_backtest
from quant_a.backtest.metrics import compute_metrics
from quant_a.backtest.report import (
    build_closed_trades,
    build_industry_win_rate,
    build_monthly_win_rate,
    build_rebalance_stats,
    build_yearly_stats,
    plot_equity_drawdown,
    summarize_trades,
)
from quant_a.backtest.validation import validate_execution_rules
from quant_a.config.loader import load_config
from quant_a.data.panel_builder import build_panel
from quant_a.data.quality import check_panel_quality
from quant_a.data.store import LocalStore
from quant_a.data.tushare_client import TuShareClient
from quant_a.features.precompute import precompute_features, precompute_index_features
from quant_a.research.metadata import build_run_metadata
from quant_a.research.snapshot import build_research_snapshot
from quant_a.research.rolling_validation import build_rolling_validation


def _estimate_resume_lookback_days(cfg: dict) -> int:
    entry_cfg = cfg["strategy"]["entry"]
    exit_cfg = cfg["strategy"]["exit"]
    regime_cfg = cfg.get("strategy", {}).get("regime_filter", {})
    lookbacks = [
        252,
        21,
        20,
        int(entry_cfg.get("breakout_lookback", 0)),
        int(entry_cfg.get("trend_ma_days", 0)),
        int(exit_cfg.get("ma_stop_days", 0)),
        int(exit_cfg.get("atr_days", 0)),
        int(regime_cfg.get("ma_days", 0)),
    ]
    lookback = max([lb for lb in lookbacks if lb > 0] or [252])
    return int(lookback * 2)


def _resolve_auto_end_date(cfg: dict, client: TuShareClient) -> None:
    end = cfg.get("backtest", {}).get("end")
    end_key = str(end).strip().lower() if end is not None else ""
    if end_key not in {"", "auto", "yesterday", "prev_trading_day"}:
        return
    exchange = cfg["backtest"]["calendar_exchange"]
    today = pd.Timestamp.today().normalize()
    target = today - pd.Timedelta(days=1)
    start = target - pd.Timedelta(days=60)
    cal = client.trade_cal(
        exchange=exchange,
        start_date=start.strftime("%Y%m%d"),
        end_date=target.strftime("%Y%m%d"),
    )
    cal = cal[cal["is_open"] == 1]
    if not cal.empty:
        resolved = str(cal["cal_date"].iloc[-1])
    else:
        resolved = target.strftime("%Y%m%d")
    cfg["backtest"]["end"] = resolved


def main() -> None:
    parser = argparse.ArgumentParser(description="A-share event-driven backtest")
    parser.add_argument("--config", required=True, help="Path to config YAML")
    parser.add_argument(
        "--out", default="outputs/runs/default", help="Output directory"
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    os.makedirs(args.out, exist_ok=True)

    resume_state = None
    prev_equity = None
    prev_trades = None
    resume_cfg = cfg.get("backtest", {})
    if resume_cfg.get("resume", False):
        resume_dir = resume_cfg.get("resume_from", args.out)
        state_path = os.path.join(resume_dir, "state.json")
        if not os.path.exists(state_path):
            raise FileNotFoundError(f"Missing resume state: {state_path}")
        with open(state_path, "r", encoding="utf-8") as f:
            resume_state = json.load(f)
        last_date = str(resume_state.get("last_date", ""))
        if last_date:
            lookback_days = resume_cfg.get("resume_lookback_days")
            if lookback_days is None:
                lookback_days = _estimate_resume_lookback_days(cfg)
            lookback_days = int(lookback_days)
            start_dt = pd.to_datetime(last_date) - pd.Timedelta(days=lookback_days)
            orig_start = pd.to_datetime(cfg["backtest"]["start"])
            if start_dt < orig_start:
                start_dt = orig_start
            if start_dt > pd.to_datetime(last_date):
                start_dt = pd.to_datetime(last_date)
            cfg["backtest"]["start"] = start_dt.strftime("%Y%m%d")
        prev_equity_path = os.path.join(resume_dir, "equity_curve.csv")
        prev_trades_path = os.path.join(resume_dir, "trades.csv")
        if os.path.exists(prev_equity_path):
            try:
                prev_equity = pd.read_csv(prev_equity_path)
            except pd.errors.EmptyDataError:
                prev_equity = pd.DataFrame()
        if os.path.exists(prev_trades_path):
            try:
                prev_trades = pd.read_csv(prev_trades_path)
            except pd.errors.EmptyDataError:
                prev_trades = pd.DataFrame()

    client = TuShareClient(
        token=cfg["tushare"]["token"], timeout=int(cfg["tushare"].get("timeout", 30))
    )
    _resolve_auto_end_date(cfg, client)
    start_dt = pd.to_datetime(cfg["backtest"]["start"])
    end_dt = pd.to_datetime(cfg["backtest"]["end"])
    if end_dt < start_dt:
        raise ValueError(
            f"backtest.end {cfg['backtest']['end']} is earlier than backtest.start {cfg['backtest']['start']}."
        )
    panel, dates, index_panel = build_panel(client, cfg)
    quality_cfg = cfg.get("data", {}).get("quality_check", {})
    quality_report = None
    if quality_cfg.get("enabled", False):
        quality_report = check_panel_quality(panel, dates)
    panel = precompute_features(panel, cfg)
    index_panel = precompute_index_features(index_panel, cfg)

    equity_df, trades_df, state = run_backtest(
        panel, dates, index_panel, cfg, resume_state=resume_state
    )
    if resume_state is not None:
        if prev_equity is not None and not prev_equity.empty and not equity_df.empty:
            equity_df = pd.concat(
                [prev_equity, equity_df.iloc[1:]], ignore_index=True
            )
        if prev_trades is not None and not prev_trades.empty and not trades_df.empty:
            trades_df = pd.concat([prev_trades, trades_df], ignore_index=True)
    metrics = compute_metrics(equity_df, trades_df)
    trade_summary = summarize_trades(trades_df)
    closed_trades = build_closed_trades(trades_df)
    yearly_stats = build_yearly_stats(equity_df)
    monthly_win_rate = build_monthly_win_rate(closed_trades)
    industry_win_rate = pd.DataFrame()
    if not closed_trades.empty:
        industry_map = {}
        store = LocalStore.from_config(cfg)
        stock_basic = store.load_df_safe("stock_basic_L") if store else None
        if stock_basic is None or stock_basic.empty:
            stock_basic = client.stock_basic(list_status="L")
            if store is not None and stock_basic is not None:
                store.save_df("stock_basic_L", stock_basic)
        if stock_basic is not None and not stock_basic.empty and "industry" in stock_basic.columns:
            industry_map = dict(zip(stock_basic["ts_code"], stock_basic["industry"]))
        industry_win_rate = build_industry_win_rate(closed_trades, industry_map)
    rebalance_stats = build_rebalance_stats(panel, dates, index_panel, cfg)
    validation_cfg = cfg.get("execution", {}).get("validation", {})
    exec_validation = None
    if validation_cfg.get("enabled", False):
        exec_validation = validate_execution_rules(panel, cfg)

    equity_path = os.path.join(args.out, "equity_curve.csv")
    trades_path = os.path.join(args.out, "trades.csv")
    metrics_path = os.path.join(args.out, "metrics.json")
    trade_summary_path = os.path.join(args.out, "trade_summary.json")
    rebalance_path = os.path.join(args.out, "rebalance_stats.csv")
    validation_path = os.path.join(args.out, "execution_validation.json")
    quality_path = os.path.join(args.out, "data_quality.json")
    rejected_path = os.path.join(args.out, "rejections.csv")
    state_path = os.path.join(args.out, "state.json")
    closed_trades_path = os.path.join(args.out, "closed_trades.csv")
    yearly_path = os.path.join(args.out, "yearly_stats.csv")
    monthly_win_rate_path = os.path.join(args.out, "monthly_win_rate.csv")
    industry_win_rate_path = os.path.join(args.out, "industry_win_rate.csv")
    meta_path = os.path.join(args.out, "run_meta.json")
    research_snapshot_path = os.path.join(args.out, "research_snapshot.json")
    rolling_validation_path = os.path.join(args.out, "rolling_validation.json")

    equity_df.to_csv(equity_path, index=False)
    trades_df.to_csv(trades_path, index=False)
    if not trades_df.empty:
        trades_df[trades_df["status"] == "rejected"].to_csv(
            rejected_path, index=False
        )
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=True, indent=2)
    with open(trade_summary_path, "w", encoding="utf-8") as f:
        json.dump(trade_summary, f, ensure_ascii=True, indent=2)
    if exec_validation is not None:
        with open(validation_path, "w", encoding="utf-8") as f:
            json.dump(exec_validation, f, ensure_ascii=True, indent=2)
    rebalance_stats.to_csv(rebalance_path, index=False)
    if quality_report is not None:
        with open(quality_path, "w", encoding="utf-8") as f:
            json.dump(quality_report, f, ensure_ascii=True, indent=2)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=True, indent=2)
    if not closed_trades.empty:
        closed_trades.to_csv(closed_trades_path, index=False)
    if not yearly_stats.empty:
        yearly_stats.to_csv(yearly_path, index=False)
    if not monthly_win_rate.empty:
        monthly_win_rate.to_csv(monthly_win_rate_path, index=False)
    if not industry_win_rate.empty:
        industry_win_rate.to_csv(industry_win_rate_path, index=False)

    repo_root = Path(__file__).resolve().parents[3]
    meta = build_run_metadata(cfg, args.config, repo_root=repo_root)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=True, indent=2)

    research_snapshot = build_research_snapshot(state, metrics, quality_report)
    with open(research_snapshot_path, "w", encoding="utf-8") as f:
        json.dump(research_snapshot, f, ensure_ascii=True, indent=2)

    rolling_cfg = cfg.get("research", {}).get("rolling_validation", {})
    rolling_validation = build_rolling_validation(
        equity_df,
        window_days=int(rolling_cfg.get("window_days", 60)),
        step_days=int(rolling_cfg.get("step_days", 20)),
    )
    with open(rolling_validation_path, "w", encoding="utf-8") as f:
        json.dump(rolling_validation, f, ensure_ascii=True, indent=2)

    plot_equity_drawdown(equity_df, args.out)


if __name__ == "__main__":
    main()
