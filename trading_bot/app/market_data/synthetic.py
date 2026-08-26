"""Synthetic price generation for tests and research -- never used for
real backtests. Same generator as research/stage2_strategy_math_spec.ipynb:
a deterministic exponential trend with i.i.d. (non-cumulative) multiplicative
daily noise, so a fixture reliably exhibits "this is an uptrend" regardless
of random seed, unlike a GBM random walk where high volatility can
overwhelm the drift by chance.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.market_data.bars import PriceHistory


def trending_series(
    index: pd.DatetimeIndex,
    annual_drift: float,
    annual_vol: float,
    s0: float = 100.0,
    seed: int = 0,
) -> pd.Series:
    rng = np.random.default_rng(seed)
    n = len(index)
    t = np.arange(n)
    trend = s0 * np.exp(annual_drift * t / 252)
    daily_vol = annual_vol / np.sqrt(252)
    noise = rng.normal(0, daily_vol, n)
    return pd.Series(trend * (1 + noise), index=index)


def generate_synthetic_history(
    specs: dict[str, dict[str, float]],
    dates: pd.DatetimeIndex,
) -> PriceHistory:
    """`specs` maps symbol -> {"annual_drift", "annual_vol", "seed"}.

    Open is modeled as the prior day's close (no overnight gap) -- a
    simplification documented in the Stage 2 spec; real intraday/overnight
    gap modeling is out of scope for this synthetic generator.
    """
    close = pd.DataFrame({
        symbol: trending_series(
            dates,
            annual_drift=params["annual_drift"],
            annual_vol=params["annual_vol"],
            seed=int(params.get("seed", 0)),
        )
        for symbol, params in specs.items()
    })
    open_ = close.shift(1)
    open_.iloc[0] = close.iloc[0]
    return PriceHistory(close=close, open=open_)
