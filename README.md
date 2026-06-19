# quant_a

Minimal A-share (China) event-driven backtest framework using TuShare Pro.

## Quick start

```bash
export TUSHARE_TOKEN="your_token"
python -m quant_a.cli.run --config configs/momentum_breakout.yaml --out outputs/runs/test01
```

Outputs:

- `equity_curve.csv`
- `trades.csv`
- `metrics.json`
- `run_meta.json` (配置哈希、代码版本、数据区间和费用模型)
- `research_snapshot.json` (只读持仓、浮盈亏、风险与数据警告)

The framework supports research and read-only trading assistance. It never submits broker orders automatically.

## Repository hygiene

Generated backtest outputs, local CSV data, caches, and virtual environments are excluded from source control. Keep reproducible sample data under `tests/fixtures/` when tests need committed data.

## Roadmap

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for reproducibility, validation, and read-only MCP expansion priorities.
