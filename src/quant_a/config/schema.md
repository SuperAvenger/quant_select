# Config Schema

Required fields:

- `tushare.token_env`: environment variable name for TuShare token (no inline token)
- `backtest.start` / `backtest.end`: `YYYYMMDD` (end can be `auto` for previous trading day)
- `data.adj`: `qfq` / `hfq`
- `benchmark.ts_code`: index code, e.g. `000300.SH`
- `strategy.name`: `momentum_breakout` / `mean_reversion_rebound`
- `strategy.rebalance`: `M` (monthly) / `D` (daily)
- `strategy.top_n`
- `strategy.regime_filter.enabled` / `index_ts_code` / `ma_days`
- `strategy.ranking.use_52w_high` / `use_mom_12_1` / `w_52w_high` / `w_mom_12_1`
- `strategy.entry.breakout_lookback` / `volume_ratio_min` / `trend_ma_days`
- `strategy.exit.use_ma_stop` / `ma_stop_days` / `use_atr_trailing` / `atr_days` / `atr_k`
- `strategy.entry.ret_5_max` / `ret_20_max` / `rsi_max` / `rebound_lookback`
- `strategy.exit.mean_revert_ma_days` / `stop_loss_pct` / `take_profit_pct` / `max_hold_days`
- `strategy.ranking.use_ret_5` / `use_ret_20` / `w_ret_5` / `w_ret_20`
- `execution.fill_price`: `next_open`
- `execution.limit_rule.enabled` / `mode`: `conservative` or `optimistic`
- `execution.t_plus_one`
- `execution.slippage_bps` / `commission_bps` / `stamp_tax_bps`
- `execution.commission_bps_by_prefix`: optional prefix → commission bps overrides
- `execution.stamp_tax_bps_by_prefix`: optional prefix → stamp tax bps overrides
- `execution.min_commission`: minimum commission amount (currency units)
- `execution.max_turnover`
- `risk.weight_scheme` / `max_weight_per_name`

Optional fields:

- `backtest.resume`: resume from previous `state.json` in output dir
- `backtest.resume_from`: path to prior run directory (defaults to `--out`)
- `backtest.resume_lookback_days`: calendar lookback window for indicator warmup
- `data.cache_dir`: local cache directory for TuShare responses (omit to disable)
- `data.store_format`: `parquet` or `csv` (falls back to `csv` if parquet engine missing)
- `data.pull_mode`: `by_ts_code` (default) or `by_trade_date`
- `data.incremental`: enable incremental cache reuse for by-date pulls (default true)
- `data.refetch_empty`: refetch empty cached files (default true)
- `data.pull_workers`: number of parallel workers for `by_trade_date` (default 1)
- `data.pull_prefetch`: number of in-flight dates to prefetch (default 2x workers)
- `data.pull_page_limit`: optional page size for daily/adj_factor pagination
- `data.pull_retries`: retry count for daily/adj_factor requests (default 3)
- `data.pull_retry_sleep`: base sleep seconds between retries (default 2.0)
- `data.pull_rate_per_min`: max API calls per minute across workers (omit to disable)
- `data.pull_fallback_single`: retry failed dates sequentially (default false)
- `data.quality_check.enabled`: emit `data_quality.json` diagnostics
- `execution.validation.enabled`: emit execution rule validation summary
- `execution.lot_size`: base lot size for order sizing (default 100)
- `execution.lot_size_by_prefix`: optional prefix → lot size overrides
- `strategy.regime_filter.momentum_days` / `momentum_min`: index momentum filter (optional)
- `strategy.ranking.use_low_vol` / `w_low_vol` / `low_vol_days`: low-volatility ranking factor
- `universe.max_names`: cap number of stocks for faster runs
