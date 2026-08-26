"""Loads historical bars from CSV files for backtesting against real data.
One CSV per symbol, filename `<SYMBOL>.csv`, columns: date,open,close (date
parseable by pandas, close already split/dividend adjusted). This is a
deliberately simple v1 -- a real Alpaca historical-data adapter is Stage 9
scope, not Stage 3.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.market_data.bars import PriceHistory


def load_price_history_from_csv(directory: Path | str, symbols: list[str]) -> PriceHistory:
    directory = Path(directory)
    close_cols = {}
    open_cols = {}

    for symbol in symbols:
        path = directory / f"{symbol}.csv"
        if not path.exists():
            raise FileNotFoundError(f"No CSV found for {symbol} at {path}")
        df = pd.read_csv(path, parse_dates=["date"], index_col="date").sort_index()
        missing = {"open", "close"} - set(df.columns)
        if missing:
            raise ValueError(f"{path} is missing required column(s): {missing}")
        close_cols[symbol] = df["close"]
        open_cols[symbol] = df["open"]

    close = pd.DataFrame(close_cols)
    open_ = pd.DataFrame(open_cols)
    return PriceHistory(close=close, open=open_)
