"""Historical price container used by the backtester (and, later, the live
engine). Deliberately minimal: two aligned DataFrames, nothing else."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class PriceHistory:
    """`close` is used for signal computation (adjusted close, so returns
    already account for splits/dividends). `open` is the price at which
    the backtest engine fills orders on the bar following a signal.

    Both must share the same DatetimeIndex and the same set of columns
    (one column per symbol) -- enforced in __post_init__ so a misaligned
    history fails loudly at construction, not partway through a backtest.
    """

    close: pd.DataFrame
    open: pd.DataFrame

    def __post_init__(self) -> None:
        if not self.close.index.equals(self.open.index):
            raise ValueError("close and open must share the same DatetimeIndex")
        if set(self.close.columns) != set(self.open.columns):
            raise ValueError("close and open must have the same symbol columns")

    @property
    def symbols(self) -> list[str]:
        return list(self.close.columns)

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.close.index
