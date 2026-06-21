import pandas as pd
import pytest

from quant_a.research.rolling_validation import build_rolling_validation


def test_rolling_validation_reports_stability_windows():
    equity = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=10, freq="D"),
            "equity": [100, 102, 101, 105, 106, 104, 108, 110, 109, 112],
        }
    )

    result = build_rolling_validation(equity, window_days=5, step_days=3)

    assert result["summary"]["window_count"] == 3
    assert result["summary"]["positive_window_rate"] == 1.0
    assert result["windows"][-1]["end"] == "2026-01-10"
    assert result["interpretation"].startswith("Overlapping-window")


def test_rolling_validation_handles_insufficient_history():
    equity = pd.DataFrame({"date": ["2026-01-01"], "equity": [100]})
    result = build_rolling_validation(equity, window_days=5, step_days=2)
    assert result["summary"]["window_count"] == 0


def test_rolling_validation_rejects_invalid_equity():
    equity = pd.DataFrame(
        {"date": ["2026-01-01", "2026-01-02"], "equity": [100, 0]}
    )
    with pytest.raises(ValueError, match="greater than zero"):
        build_rolling_validation(equity, window_days=2, step_days=1)
