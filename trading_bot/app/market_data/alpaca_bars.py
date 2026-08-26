"""Real Alpaca market-data adapter for Stage 11: fetches historical daily
bars (for strategy signals) and latest trade prices (for current_prices),
shaped into exactly what TradingEngine.run_rebalance_cycle expects -- a
close-price DataFrame indexed by normalized, tz-naive session dates, and a
plain {symbol: price} dict.

Depends on alpaca-py's StockHistoricalDataClient through a narrow
Protocol, so tests fake it completely -- no real network calls or
credentials. Market data itself doesn't differ between paper and live
Alpaca accounts (same real market, same endpoint), so unlike
app/broker/alpaca.py this adapter is not mode-aware.

Bars are requested with Adjustment.ALL (splits and dividends) -- a
momentum strategy comparing prices across time must not see a false
signal break from an ETF distribution or a split that a raw price series
would show as a cliff.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

import pandas as pd
from alpaca.data.enums import Adjustment
from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame


class AlpacaDataClient(Protocol):
    """The slice of alpaca-py's StockHistoricalDataClient this adapter
    depends on -- narrow enough to fake completely in tests."""

    def get_stock_bars(self, request_params): ...
    def get_stock_latest_trade(self, request_params): ...


def _to_naive_date(ts) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(None)
    return ts.normalize()


class AlpacaMarketData:
    def __init__(self, api_key: str, secret_key: str, data_client: AlpacaDataClient | None = None) -> None:
        if data_client is not None:
            self._client = data_client
        else:
            from alpaca.data.historical import StockHistoricalDataClient

            self._client = StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)

    def get_daily_close_history(self, symbols: list[str], start: datetime, end: datetime) -> pd.DataFrame:
        request = StockBarsRequest(
            symbol_or_symbols=list(symbols), start=start, end=end,
            timeframe=TimeFrame.Day, adjustment=Adjustment.ALL,
        )
        bar_set = self._client.get_stock_bars(request)

        series = {}
        for symbol in symbols:
            bars = bar_set.data.get(symbol, [])
            if not bars:
                continue
            index = pd.DatetimeIndex([_to_naive_date(b.timestamp) for b in bars])
            series[symbol] = pd.Series([b.close for b in bars], index=index)
        return pd.DataFrame(series)

    def get_latest_prices(self, symbols: list[str]) -> dict[str, float]:
        request = StockLatestTradeRequest(symbol_or_symbols=list(symbols))
        trades = self._client.get_stock_latest_trade(request)
        return {symbol: trade.price for symbol, trade in trades.items()}
