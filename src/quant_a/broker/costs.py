from __future__ import annotations


def calc_fee(
    notional: float,
    side: str,
    commission_bps: float,
    stamp_tax_bps: float,
    min_commission: float = 0.0,
) -> float:
    fee = notional * commission_bps / 10000.0
    if min_commission > 0 and fee > 0:
        fee = max(fee, min_commission)
    if side == "SELL":
        fee += notional * stamp_tax_bps / 10000.0
    return fee
