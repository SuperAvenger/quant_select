from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Order:
    ts_code: str
    side: str  # BUY / SELL
    qty: int
    signal_date: str
    exec_date: str
    reason: str


@dataclass
class Fill:
    ts_code: str
    side: str
    qty: int
    price: float
    exec_date: str
    fee: float
    status: str
    reason: str


@dataclass
class Position:
    qty: int
    avg_cost: float
    last_buy_date: str
    highest_close_since_entry: float
