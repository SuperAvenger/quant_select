from __future__ import annotations

from typing import Dict

import pandas as pd


def _to_datetime(date_str: str) -> pd.Timestamp:
    return pd.to_datetime(date_str, format="%Y%m%d")


def filter_universe(df: pd.DataFrame, cfg: Dict) -> pd.DataFrame:
    universe_cfg = cfg.get("universe", {})
    if universe_cfg.get("exclude_st", False):
        df = df[~df["name"].str.contains("ST", case=False, na=False)]
    min_list_days = universe_cfg.get("min_list_days")
    if min_list_days:
        start_date = _to_datetime(cfg["backtest"]["start"])
        threshold = start_date - pd.Timedelta(days=int(min_list_days))
        df = df[_to_datetime(df["list_date"]) <= threshold]
    max_names = universe_cfg.get("max_names")
    if max_names:
        df = df.sort_values("ts_code").head(int(max_names))
    return df
