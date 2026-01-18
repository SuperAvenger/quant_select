from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from quant_a.data.store import LocalStore
from quant_a.data.tushare_client import TuShareClient
from quant_a.data.universe import filter_universe

PRICE_COLS = ["open", "high", "low", "close"]


def _maybe_cached(
    store: Optional[LocalStore], key: str, fetcher: Callable[[], pd.DataFrame]
) -> pd.DataFrame:
    if store is None:
        return fetcher()
    return store.get_or_fetch(key, fetcher)


def _fetch_paged(
    fetcher: Callable[[int, Optional[int]], pd.DataFrame],
    page_limit: Optional[int],
    rate_limiter: Optional["RateLimiter"],
) -> pd.DataFrame:
    if not page_limit or page_limit <= 0:
        if rate_limiter is not None:
            rate_limiter.wait()
        return fetcher(0, None)
    frames = []
    offset = 0
    last_signature = None
    while True:
        if rate_limiter is not None:
            rate_limiter.wait()
        df = fetcher(offset, page_limit)
        if df is None or df.empty:
            break
        frames.append(df)
        signature = None
        if "ts_code" in df.columns and len(df) > 0:
            signature = (len(df), str(df["ts_code"].iloc[0]), str(df["ts_code"].iloc[-1]))
        if len(df) < page_limit:
            break
        if last_signature is not None and signature == last_signature:
            break
        last_signature = signature
        offset += page_limit
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _fetch_paged_with_retry(
    fetcher: Callable[[int, Optional[int]], pd.DataFrame],
    page_limit: Optional[int],
    rate_limiter: Optional["RateLimiter"],
    retries: int,
    retry_sleep: float,
) -> pd.DataFrame:
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return _fetch_paged(fetcher, page_limit, rate_limiter)
        except Exception as exc:
            last_exc = exc
            if attempt >= retries:
                break
            time.sleep(retry_sleep * (2 ** attempt))
    if last_exc is not None:
        raise last_exc
    return pd.DataFrame()


def _maybe_cached_paged(
    store: Optional[LocalStore],
    key: str,
    fetcher: Callable[[int, Optional[int]], pd.DataFrame],
    page_limit: Optional[int],
    rate_limiter: Optional["RateLimiter"],
    retries: int,
    retry_sleep: float,
) -> pd.DataFrame:
    if store is not None:
        cached = store.load_df_safe(key)
        if cached is not None:
            return cached
    df = _fetch_paged_with_retry(fetcher, page_limit, rate_limiter, retries, retry_sleep)
    if store is not None:
        store.save_df(key, df)
    return df


class RateLimiter:
    def __init__(self, per_minute: Optional[int]) -> None:
        self._interval = 0.0
        if per_minute and per_minute > 0:
            self._interval = 60.0 / float(per_minute)
        self._lock = threading.Lock()
        self._next_allowed = time.monotonic()

    def wait(self) -> None:
        if self._interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            if now < self._next_allowed:
                wait = self._next_allowed - now
                self._next_allowed += self._interval
            else:
                wait = 0.0
                self._next_allowed = now + self._interval
        if wait > 0:
            time.sleep(wait)


def _apply_adj_factor(
    df: pd.DataFrame,
    adj_df: pd.DataFrame,
    adj_mode: str,
    base_factors: Dict[str, float],
) -> pd.DataFrame:
    if adj_df is None or adj_df.empty:
        return df
    adj_df = adj_df[["ts_code", "adj_factor"]].copy()
    adj_df["adj_factor"] = pd.to_numeric(adj_df["adj_factor"], errors="coerce")
    df = df.merge(adj_df, on="ts_code", how="left")
    if adj_mode == "hfq":
        factor = df["adj_factor"]
        for col in PRICE_COLS:
            df[col] = df[col] * factor
    elif adj_mode == "qfq":
        missing = df["ts_code"].map(base_factors).isna()
        if missing.any():
            first_factors = df.loc[missing, ["ts_code", "adj_factor"]].dropna()
            for ts_code, factor in first_factors.itertuples(index=False):
                base_factors.setdefault(ts_code, float(factor))
        base = df["ts_code"].map(base_factors)
        ratio = df["adj_factor"] / base
        valid = ratio.notna()
        if valid.any():
            df.loc[valid, PRICE_COLS] = df.loc[valid, PRICE_COLS].multiply(
                ratio[valid], axis=0
            )
    df = df.drop(columns=["adj_factor"])
    return df


def _build_stock_panel(
    client: TuShareClient,
    cfg: Dict,
    ts_codes: List[str],
    store: Optional[LocalStore],
) -> pd.DataFrame:
    start = cfg["backtest"]["start"]
    end = cfg["backtest"]["end"]
    adj = cfg["data"]["adj"]
    frames = []
    for ts_code in ts_codes:
        key = f"pro_bar_{ts_code}_{start}_{end}_{adj}"
        df = _maybe_cached(
            store,
            key,
            lambda ts_code=ts_code: client.pro_bar(
                ts_code=ts_code, start_date=start, end_date=end, adj=adj
            ),
        )
        if df is None or df.empty:
            continue
        df = df.copy()
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    panel = pd.concat(frames, ignore_index=True)
    panel["trade_date"] = panel["trade_date"].astype(str)
    return panel


def _build_stock_panel_by_date(
    client: TuShareClient,
    cfg: Dict,
    dates: List[str],
    ts_codes: List[str],
    store: Optional[LocalStore],
) -> pd.DataFrame:
    data_cfg = cfg.get("data", {})
    adj_mode = str(data_cfg.get("adj", "")).lower()
    use_adj = adj_mode in {"qfq", "hfq"}
    incremental = bool(data_cfg.get("incremental", True))
    refetch_empty = bool(data_cfg.get("refetch_empty", True))
    page_limit = data_cfg.get("pull_page_limit")
    try:
        page_limit = int(page_limit) if page_limit is not None else None
    except (TypeError, ValueError):
        page_limit = None
    pull_workers = int(data_cfg.get("pull_workers", 1))
    if pull_workers < 1:
        pull_workers = 1
    pull_prefetch = int(data_cfg.get("pull_prefetch", max(2, pull_workers * 2)))
    if pull_prefetch < 1:
        pull_prefetch = 1
    pull_retries = int(data_cfg.get("pull_retries", 3))
    if pull_retries < 0:
        pull_retries = 0
    pull_retry_sleep = float(data_cfg.get("pull_retry_sleep", 2.0))
    if pull_retry_sleep < 0:
        pull_retry_sleep = 0.0
    pull_fallback_single = bool(data_cfg.get("pull_fallback_single", False))
    pull_rate_per_min = data_cfg.get("pull_rate_per_min")
    try:
        pull_rate_per_min = (
            int(pull_rate_per_min) if pull_rate_per_min is not None else None
        )
    except (TypeError, ValueError):
        pull_rate_per_min = None
    rate_limiter = RateLimiter(pull_rate_per_min)
    code_set = set(ts_codes)
    base_factors: Dict[str, float] = {}
    frames = []
    seen_daily_dates: set[str] = set()
    seen_adj_dates: set[str] = set()
    failed_dates: Dict[str, str] = {}

    cached_daily_dates: set[str] = set()
    cached_adj_dates: set[str] = set()
    if store is not None and incremental:
        cached_daily_dates = store.list_cached_dates("daily_")
        cached_adj_dates = store.list_cached_dates("adj_factor_")
        cached_daily_dates.update(store.get_manifest_dates("daily"))
        cached_adj_dates.update(store.get_manifest_dates("adj_factor"))

    def fetch_bundle(trade_date: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
        key = f"daily_{trade_date}"
        daily_df: Optional[pd.DataFrame] = None
        if store is not None and incremental and trade_date in cached_daily_dates:
            daily_df = store.load_df_safe(key)
            if daily_df is not None and daily_df.empty and refetch_empty:
                daily_df = None
        if daily_df is None:
            daily_df = _maybe_cached_paged(
                store,
                key,
                lambda offset, limit, trade_date=trade_date: client.daily_by_date(
                    trade_date, offset=offset, limit=limit
                ),
                page_limit,
                rate_limiter,
                pull_retries,
                pull_retry_sleep,
            )
        adj_df = pd.DataFrame()
        if use_adj:
            adj_key = f"adj_factor_{trade_date}"
            if store is not None and incremental and trade_date in cached_adj_dates:
                adj_df = store.load_df_safe(adj_key)
                if adj_df is not None and adj_df.empty and refetch_empty:
                    adj_df = None
            if adj_df is None or (adj_df.empty and refetch_empty):
                adj_df = _maybe_cached_paged(
                    store,
                    adj_key,
                    lambda offset, limit, trade_date=trade_date: client.adj_factor_by_date(
                        trade_date, offset=offset, limit=limit
                    ),
                    page_limit,
                    rate_limiter,
                    pull_retries,
                    pull_retry_sleep,
                )
        return daily_df, adj_df

    def process_bundle(trade_date: str, daily_df: pd.DataFrame, adj_df: pd.DataFrame) -> None:
        if daily_df is None or daily_df.empty:
            return
        seen_daily_dates.add(trade_date)
        if use_adj and adj_df is not None and not adj_df.empty:
            seen_adj_dates.add(trade_date)
        df = daily_df.copy()
        if code_set:
            df = df[df["ts_code"].isin(code_set)]
        if df.empty:
            return
        df["trade_date"] = df["trade_date"].astype(str)
        for col in PRICE_COLS + ["vol", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if use_adj:
            df = _apply_adj_factor(df, adj_df, adj_mode, base_factors)
        frames.append(df)

    if pull_workers <= 1:
        for trade_date in dates:
            try:
                daily_df, adj_df = fetch_bundle(trade_date)
            except Exception as exc:
                failed_dates[trade_date] = str(exc)
                continue
            process_bundle(trade_date, daily_df, adj_df)
    else:
        with ThreadPoolExecutor(max_workers=pull_workers) as executor:
            futures: Dict[str, "concurrent.futures.Future[Tuple[pd.DataFrame, pd.DataFrame]]"] = {}
            next_idx = 0

            def submit_next() -> bool:
                nonlocal next_idx
                if next_idx >= len(dates):
                    return False
                trade_date = dates[next_idx]
                next_idx += 1
                futures[trade_date] = executor.submit(fetch_bundle, trade_date)
                return True

            for _ in range(min(pull_prefetch, len(dates))):
                submit_next()

            for trade_date in dates:
                if trade_date not in futures:
                    futures[trade_date] = executor.submit(fetch_bundle, trade_date)
                try:
                    daily_df, adj_df = futures.pop(trade_date).result()
                except Exception as exc:
                    failed_dates[trade_date] = str(exc)
                    while len(futures) < pull_prefetch:
                        if not submit_next():
                            break
                    continue
                process_bundle(trade_date, daily_df, adj_df)
                while len(futures) < pull_prefetch:
                    if not submit_next():
                        break

    if pull_fallback_single and failed_dates:
        retry_dates = sorted(failed_dates.keys())
        failed_dates = {}
        for trade_date in retry_dates:
            try:
                daily_df, adj_df = fetch_bundle(trade_date)
            except Exception as exc:
                failed_dates[trade_date] = str(exc)
                continue
            process_bundle(trade_date, daily_df, adj_df)
    if not frames:
        return pd.DataFrame()
    panel = pd.concat(frames, ignore_index=True)
    panel["trade_date"] = panel["trade_date"].astype(str)
    if store is not None and incremental:
        store.record_dates("daily", seen_daily_dates)
        if use_adj:
            store.record_dates("adj_factor", seen_adj_dates)
    if failed_dates and store is not None:
        failure_path = os.path.join(store.root, "pull_failures.json")
        payload = {
            "failed_dates": failed_dates,
            "count": len(failed_dates),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        with open(failure_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=True, indent=2)
    return panel


def _build_index_panel(
    client: TuShareClient,
    cfg: Dict,
    index_codes: List[str],
    store: Optional[LocalStore],
) -> pd.DataFrame:
    start = cfg["backtest"]["start"]
    end = cfg["backtest"]["end"]
    frames = []
    for ts_code in index_codes:
        key = f"index_bar_{ts_code}_{start}_{end}"
        df = _maybe_cached(
            store,
            key,
            lambda ts_code=ts_code: client.index_bar(
                ts_code=ts_code, start_date=start, end_date=end
            ),
        )
        if df is None or df.empty:
            continue
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    panel = pd.concat(frames, ignore_index=True)
    panel["trade_date"] = panel["trade_date"].astype(str)
    return panel


def build_panel(
    client: TuShareClient, cfg: Dict
) -> Tuple[pd.DataFrame, List[str], pd.DataFrame]:
    store = LocalStore.from_config(cfg)
    start = cfg["backtest"]["start"]
    end = cfg["backtest"]["end"]
    exchange = cfg["backtest"]["calendar_exchange"]

    cal = _maybe_cached(
        store,
        f"trade_cal_{exchange}_{start}_{end}",
        lambda: client.trade_cal(
            exchange=exchange,
            start_date=start,
            end_date=end,
        ),
    )
    cal = cal[cal["is_open"] == 1].sort_values("cal_date")
    dates = cal["cal_date"].astype(str).tolist()

    stocks = _maybe_cached(
        store,
        "stock_basic_L",
        lambda: client.stock_basic(list_status="L"),
    )
    stocks = filter_universe(stocks, cfg)
    ts_codes = stocks["ts_code"].tolist()

    pull_mode = str(cfg.get("data", {}).get("pull_mode", "by_ts_code")).lower()
    if pull_mode in {"by_trade_date", "by_date"}:
        panel = _build_stock_panel_by_date(client, cfg, dates, ts_codes, store)
    else:
        panel = _build_stock_panel(client, cfg, ts_codes, store)
    if panel.empty:
        return panel, dates, pd.DataFrame()

    limit_df = _maybe_cached(
        store,
        f"stk_limit_{start}_{end}",
        lambda: client.stk_limit(start_date=start, end_date=end),
    )
    if limit_df is None:
        limit_df = pd.DataFrame()
    suspend_df = _maybe_cached(
        store,
        f"suspend_d_{start}_{end}",
        lambda: client.suspend_d(start_date=start, end_date=end),
    )
    if suspend_df is None:
        suspend_df = pd.DataFrame()

    if not limit_df.empty:
        limit_df = limit_df[["ts_code", "trade_date", "up_limit", "down_limit"]]
        limit_df["trade_date"] = limit_df["trade_date"].astype(str)
        panel = panel.merge(limit_df, on=["ts_code", "trade_date"], how="left")
    else:
        panel["up_limit"] = pd.NA
        panel["down_limit"] = pd.NA

    if not suspend_df.empty:
        suspend_df = suspend_df[["ts_code", "trade_date"]].copy()
        suspend_df["suspend"] = 1
        suspend_df["trade_date"] = suspend_df["trade_date"].astype(str)
        panel = panel.merge(suspend_df, on=["ts_code", "trade_date"], how="left")
    else:
        panel["suspend"] = 0

    panel["suspend"] = panel["suspend"].fillna(0).astype(int)
    panel = panel.drop_duplicates(subset=["trade_date", "ts_code"])
    panel = panel.set_index(["trade_date", "ts_code"]).sort_index()

    index_codes = {cfg.get("benchmark", {}).get("ts_code")}
    regime_cfg = cfg.get("strategy", {}).get("regime_filter", {})
    if regime_cfg.get("enabled"):
        index_codes.add(regime_cfg.get("index_ts_code"))
    index_codes = [code for code in index_codes if code]
    index_panel = _build_index_panel(client, cfg, index_codes, store)
    if not index_panel.empty:
        index_panel = index_panel.drop_duplicates(subset=["trade_date", "ts_code"])
        index_panel = index_panel.set_index(["trade_date", "ts_code"]).sort_index()

    return panel, dates, index_panel
