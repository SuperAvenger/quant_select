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
