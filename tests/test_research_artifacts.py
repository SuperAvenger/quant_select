from pathlib import Path

import pytest

from quant_a.research.metadata import build_run_metadata, config_sha256
from quant_a.research.snapshot import build_research_snapshot


def sample_config():
    return {
        "tushare": {"token": "secret-token"},
        "backtest": {"start": "20260101", "end": "20260331", "calendar_exchange": "SSE"},
        "data": {"adj": "qfq"},
        "strategy": {"name": "momentum_breakout"},
        "execution": {"commission_bps": 3, "slippage_bps": 5},
        "universe": {"max_names": 300},
    }


def test_run_metadata_is_reproducible_and_never_contains_token(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    cfg = sample_config()
    metadata = build_run_metadata(cfg, "configs/test.yaml", Path(tmp_path))

    assert metadata["config_sha256"] == config_sha256(cfg)
    assert metadata["code_revision"] == "abc123"
    assert metadata["automatic_order_submission"] is False
    assert "secret-token" not in str(metadata)


def test_research_snapshot_calculates_position_risk_without_orders():
    snapshot = build_research_snapshot(
        {
            "last_date": "20260331",
            "cash": 5000,
            "equity": 16000,
            "positions": {"000001.SZ": {"qty": 1000, "avg_cost": 10.0}},
            "last_prices": {"000001.SZ": 11.0},
        },
        {"total_return": 0.1, "max_drawdown": -0.05},
    )

    assert snapshot["mode"] == "read_only_research_assistance"
    assert snapshot["automatic_order_submission"] is False
    assert snapshot["portfolio"]["gross_market_value"] == 11000
    assert snapshot["positions"][0]["unrealized_pnl"] == 1000
    assert snapshot["positions"][0]["unrealized_return"] == pytest.approx(0.1)
