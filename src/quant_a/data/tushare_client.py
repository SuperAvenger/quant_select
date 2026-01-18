from __future__ import annotations

from typing import Optional

import pandas as pd
import tushare as ts


class TuShareClient:
    def __init__(self, token: str, timeout: int = 30) -> None:
        ts.set_token(token)
        self._pro = ts.pro_api(token)
        self._timeout = timeout

    def trade_cal(self, exchange: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._pro.trade_cal(
            exchange=exchange,
            start_date=start_date,
            end_date=end_date,
            fields="exchange,cal_date,is_open",
        )

    def stock_basic(self, list_status: str = "L") -> pd.DataFrame:
        return self._pro.stock_basic(
            list_status=list_status,
            fields="ts_code,symbol,name,area,industry,list_date,market",
        )

    def pro_bar(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        adj: str = "qfq",
    ) -> pd.DataFrame:
        df = ts.pro_bar(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            adj=adj,
            factors=None,
            asset="E",
            fields="ts_code,trade_date,open,high,low,close,vol,amount",
        )
        if df is None:
            return pd.DataFrame()
        return df

    def index_bar(
        self, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        df = ts.pro_bar(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            adj=None,
            asset="I",
            fields="ts_code,trade_date,open,high,low,close,vol,amount",
        )
        if df is None:
            return pd.DataFrame()
        return df

    def daily_by_date(
        self, trade_date: str, offset: int = 0, limit: Optional[int] = None
    ) -> pd.DataFrame:
        kwargs = {"trade_date": trade_date}
        if offset:
            kwargs["offset"] = offset
        if limit:
            kwargs["limit"] = limit
        df = self._pro.daily(
            fields="ts_code,trade_date,open,high,low,close,vol,amount",
            **kwargs,
        )
        if df is None:
            return pd.DataFrame()
        return df

    def adj_factor_by_date(
        self, trade_date: str, offset: int = 0, limit: Optional[int] = None
    ) -> pd.DataFrame:
        kwargs = {"trade_date": trade_date}
        if offset:
            kwargs["offset"] = offset
        if limit:
            kwargs["limit"] = limit
        df = self._pro.adj_factor(
            fields="ts_code,trade_date,adj_factor",
            **kwargs,
        )
        if df is None:
            return pd.DataFrame()
        return df

    def stk_limit(
        self,
        start_date: str,
        end_date: str,
        ts_code: Optional[str] = None,
    ) -> pd.DataFrame:
        return self._pro.stk_limit(
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
            fields="ts_code,trade_date,up_limit,down_limit",
        )

    def suspend_d(self, start_date: str, end_date: str) -> pd.DataFrame:
        return self._pro.suspend_d(
            start_date=start_date,
            end_date=end_date,
            fields="ts_code,trade_date,suspend_type",
        )
