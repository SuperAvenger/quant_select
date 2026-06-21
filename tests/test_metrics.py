import pandas as pd
import pytest

from quant_a.backtest.metrics import compute_metrics


def test_compute_metrics_reports_return_and_drawdown():
    equity = pd.DataFrame({"equity": [100.0, 110.0, 99.0, 120.0]})
    trades = pd.DataFrame(
        [
            {
                "status": "filled",
                "exec_date": "2026-01-02",
                "ts_code": "000001.SZ",
                "side": "BUY",
                "qty": 100,
                "price": 10.0,
                "fee": 1.0,
            },
            {
                "status": "filled",
                "exec_date": "2026-01-05",
                "ts_code": "000001.SZ",
                "side": "SELL",
                "qty": 100,
                "price": 11.0,
                "fee": 1.0,
            },
        ]
    )

    result = compute_metrics(equity, trades)

    assert result["total_return"] == pytest.approx(0.2)
    assert result["max_drawdown"] == pytest.approx(-0.1)
    assert result["closed_trades"] == 1
    assert result["win_rate"] == 1.0


@pytest.mark.parametrize("values", [[0.0, 1.0], [100.0, float("nan")]])
def test_compute_metrics_rejects_invalid_equity(values):
    with pytest.raises(ValueError, match="finite and greater than zero"):
        compute_metrics(pd.DataFrame({"equity": values}), pd.DataFrame())
