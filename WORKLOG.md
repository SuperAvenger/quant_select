# Quant Select Worklog

## Day 2: Architecture Optimization & Strategy Tuning (2026-01-19)

### Summary of work done
1. **Refactored Architecture**:
   - Implemented `Strategy Registry` pattern to replace hardcoded strategy selection.
   - Decoupled `engine.py` from specific strategy implementations.
   - Extracted common logic (e.g., `compute_rebalance_dates`) to `base.py`.

2. **Strategy Optimization**:
   - **Mean Reversion**: Upgraded from Daily (D) to Weekly (W) rebalancing to reduce turnover.
   - **Momentum Breakout**: Created "Relaxed" version with looser filter conditions (60d lookback vs 120d).

3. **Full Market Validation**:
   - Removed `universe.max_names` limit in new configs to run on the entire A-share market.
   - Conducted backtests on 2016-2025 data.

### Key Findings
1. **Mean Reversion (Weekly vs Daily)**:
   - Turnover reduced from 146x to 118x.
   - Total loss reduced from -73% to -61%.
   - **Insight**: Even with weekly rebalancing, the strategy's high turnover combined with A-share transaction costs (stamp tax) makes it unviable without further optimization (e.g., lower frequency, stricter entry).

2. **Momentum Breakout (Relaxed vs Tuned)**:
   - Relaxing conditions (60d lookback) did **not** improve performance (-22% vs -21%).
   - Both versions failed to generate positive alpha in the 2016-2025 period (mostly bear/range markets).
   - **Insight**: Simple price-volume breakout strategies struggle in the current A-share regime.

### Files Created/Updated
- **Source**:
  - `src/quant_a/strategy/base.py`: Added registry & date utils.
  - `src/quant_a/strategy/__init__.py`: Export registry.
  - `src/quant_a/strategy/*.py`: Added `@register_strategy` decorators.
  - `src/quant_a/backtest/engine.py`: Updated to use factory.
- **Configs**:
  - `configs/mean_reversion_weekly.yaml`
  - `configs/momentum_breakout_relaxed.yaml`

### TODO / Next Steps
1. **Strategy Pivot**:
   - Consider **Sector Rotation** or **Low Volatility** strategies which historically perform better in A-shares.
   - Implement **Fundamental Factors** (PE/PB/ROE) filters to improve quality.
2. **Infrastructure**:
   - Implement `PortfolioManager` for centralized risk control.
   - Add **Benchmark Comparison** in plots (currently only equity curve).

## Day 1: Initial Implementation (Previous)
- Implemented a minimal A-share daily event-driven backtest framework using TuShare Pro.
- Added strict next-open execution, suspend/limit rules, and T+1 constraints.
- Implemented momentum_breakout strategy with regime filter, breakout + volume, MA/ATR exits.
- Fixed breakout logic to use prior rolling high (`shift(1)`) so signals exist.
- Corrected amount unit for liquidity filter (TuShare `amount` is in thousands).
- Added trade summary, rebalance stats, and equity/drawdown plots.
- Added `universe.max_names` cap for faster iteration runs.
