from __future__ import annotations

from typing import Any, Dict


def build_research_snapshot(
    state: Dict[str, Any],
    metrics: Dict[str, Any],
    data_quality: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a read-only portfolio view from a completed research run."""
    last_prices = state.get("last_prices", {})
    positions = []
    warnings = []
    gross_market_value = 0.0

    for code, position in sorted(state.get("positions", {}).items()):
        qty = int(position.get("qty", 0))
        avg_cost = float(position.get("avg_cost", 0.0))
        price = last_prices.get(code)
        if price is None:
            warnings.append(f"missing_latest_price:{code}")
            price = avg_cost
        price = float(price)
        market_value = qty * price
        cost_value = qty * avg_cost
        gross_market_value += market_value
        positions.append(
            {
                "ts_code": code,
                "qty": qty,
                "avg_cost": avg_cost,
                "latest_price": price,
                "market_value": market_value,
                "unrealized_pnl": market_value - cost_value,
                "unrealized_return": (price / avg_cost - 1.0) if avg_cost else None,
            }
        )

    if data_quality:
        failed = data_quality.get("failed_checks") or data_quality.get("warnings") or []
        warnings.extend(f"data_quality:{item}" for item in failed)

    equity = float(state.get("equity", 0.0))
    return {
        "schema_version": 1,
        "mode": "read_only_research_assistance",
        "automatic_order_submission": False,
        "as_of": state.get("last_date"),
        "portfolio": {
            "equity": equity,
            "cash": float(state.get("cash", 0.0)),
            "gross_market_value": gross_market_value,
            "invested_ratio": gross_market_value / equity if equity else 0.0,
            "position_count": len(positions),
        },
        "positions": positions,
        "performance": metrics,
        "warnings": warnings,
        "disclaimer": "Research output only. Review data and risk before any manual trading decision.",
    }
