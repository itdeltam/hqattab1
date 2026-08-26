"""Trend/momentum signal math. Ported from and must stay consistent with
research/stage2_strategy_math_spec.ipynb -- that notebook is the spec and
justification; this module is the implementation Stage 3's backtester (and
later the live engine) actually calls.

Every function here takes a price Series/DataFrame indexed by date and
returns values aligned to that same index. Callers (the backtest engine)
are responsible for only ever looking up a value at index t-1 or earlier
when making a decision "as of" t -- these functions do not enforce that
themselves, since they operate on whatever history they're handed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.strategy.params import StrategyParams


def trend_filter(prices: pd.Series, params: StrategyParams) -> pd.Series:
    """True where the asset is eligible (in an uptrend): price above its
    SMA and trailing total return positive. NaN-safe: False wherever
    there isn't enough history yet, never raises."""
    sma = prices.rolling(params.sma_window).mean()
    trailing_return = prices / prices.shift(params.trend_mom_window) - 1
    eligible = (prices > sma) & (trailing_return > 0)
    return eligible.fillna(False)


def realized_vol(prices: pd.Series, window: int) -> pd.Series:
    """Annualized realized volatility of daily returns."""
    return prices.pct_change().rolling(window).std() * np.sqrt(252)


def momentum_score(prices: pd.Series, params: StrategyParams) -> pd.Series:
    """Volatility-adjusted, multi-lookback momentum score. NaN until every
    configured lookback has full history -- see the skipna=False note
    below, this is deliberate, not an oversight."""
    rets = []
    for lb in params.momentum_lookbacks:
        r = prices.shift(params.momentum_skip) / prices.shift(params.momentum_skip + lb) - 1
        rets.append(r)
    # skipna=False: until every lookback has full history, a partial
    # average would silently mix a 1-lookback score with a 3-lookback
    # score, which are not comparable across assets/dates.
    avg_ret = pd.concat(rets, axis=1).mean(axis=1, skipna=False)
    vol = realized_vol(prices, params.vol_window)
    return avg_ret / vol
