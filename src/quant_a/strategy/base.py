from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Set, Type

import pandas as pd


@dataclass
class SignalContext:
    signal_date: str
    exec_date: str
    last_prices: Dict[str, float]
    cash: float


def compute_rebalance_dates(dates: List[str], freq: str) -> Set[str]:
    """Compute rebalance dates based on frequency: D (daily), W (weekly), M (monthly)."""
    if not dates:
        return set()
    
    if freq == "D":
        return set(dates)
    
    if freq == "W":
        result: Set[str] = set()
        last_week = None
        for d in dates:
            dt = pd.to_datetime(d)
            week_key = (dt.isocalendar().year, dt.isocalendar().week)
            if week_key != last_week:
                result.add(d)
                last_week = week_key
        return result
    
    if freq == "M":
        result = set()
        last_month = None
        for d in dates:
            month = d[:6]
            if month != last_month:
                result.add(d)
                last_month = month
        return result
    
    return set(dates)


_STRATEGY_REGISTRY: Dict[str, Type["BaseStrategy"]] = {}


def register_strategy(name: str) -> Callable[[Type["BaseStrategy"]], Type["BaseStrategy"]]:
    """Decorator to register a strategy class by name.
    
    Usage:
        @register_strategy("my_strategy")
        class MyStrategy(BaseStrategy):
            ...
    """
    def decorator(cls: Type["BaseStrategy"]) -> Type["BaseStrategy"]:
        if name in _STRATEGY_REGISTRY:
            raise ValueError(f"Strategy '{name}' is already registered.")
        _STRATEGY_REGISTRY[name] = cls
        return cls
    return decorator


def get_strategy(name: str) -> Type["BaseStrategy"]:
    """Get a strategy class by name."""
    if name not in _STRATEGY_REGISTRY:
        available = ", ".join(sorted(_STRATEGY_REGISTRY.keys())) or "(none)"
        raise ValueError(f"Unknown strategy '{name}'. Available: {available}")
    return _STRATEGY_REGISTRY[name]


def list_strategies() -> List[str]:
    """List all registered strategy names."""
    return sorted(_STRATEGY_REGISTRY.keys())


def create_strategy(
    name: str,
    cfg: Dict,
    dates: List[str],
    index_panel: pd.DataFrame,
) -> "BaseStrategy":
    """Factory function to create a strategy instance by name."""
    strategy_cls = get_strategy(name)
    return strategy_cls(cfg, dates, index_panel)


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies."""
    
    def __init__(self, cfg: Dict, dates: List[str], index_panel: pd.DataFrame) -> None:
        self.cfg = cfg
        self.dates = dates
        self.index_panel = index_panel

    @abstractmethod
    def generate_orders(
        self,
        panel: pd.DataFrame,
        positions: Dict[str, object],
        ctx: SignalContext,
    ) -> List[object]:
        """Generate orders based on current market state and positions."""
        raise NotImplementedError
    
    def get_rebalance_snapshot(
        self, panel: pd.DataFrame, signal_date: str
    ) -> Optional[Dict[str, object]]:
        """Optional: Return rebalance statistics for reporting."""
        return None
