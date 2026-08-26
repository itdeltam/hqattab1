import pandas as pd
import pytest

from app.market_data.synthetic import trending_series
from app.strategy.params import StrategyParams
from app.strategy.signals import momentum_score, trend_filter


@pytest.fixture
def params():
    return StrategyParams()


@pytest.fixture
def dates():
    return pd.bdate_range("2022-01-03", periods=500)


def test_trend_filter_insufficient_history_is_false_not_error(dates, params):
    prices = trending_series(dates, annual_drift=0.18, annual_vol=0.10, seed=1)
    eligible = trend_filter(prices, params)
    assert not eligible.iloc[:200].any()


def test_trend_filter_separates_uptrend_from_downtrend(dates, params):
    up = trending_series(dates, annual_drift=0.18, annual_vol=0.10, seed=1)
    down = trending_series(dates, annual_drift=-0.20, annual_vol=0.15, seed=4)

    assert trend_filter(up, params).iloc[-1]
    assert not trend_filter(down, params).iloc[-1]


def test_momentum_score_nan_until_full_history(dates, params):
    prices = trending_series(dates, annual_drift=0.18, annual_vol=0.10, seed=1)
    score = momentum_score(prices, params)
    assert score.iloc[:252].isna().all()


def test_momentum_score_requires_all_lookbacks_not_partial_average(dates, params):
    """Regression guard: pandas' .mean(axis=1) defaults to skipna=True,
    which would let the ensemble score start averaging as soon as the
    *shortest* lookback has history, silently mixing a 1-component and a
    3-component average. The score must stay NaN until every lookback in
    params.momentum_lookbacks has full history (i.e. through skip + max
    lookback), not just the shortest one."""
    prices = trending_series(dates, annual_drift=0.18, annual_vol=0.10, seed=1)
    score = momentum_score(prices, params)

    shortest_lookback_ready_idx = params.momentum_skip + min(params.momentum_lookbacks)
    assert pd.isna(score.iloc[shortest_lookback_ready_idx])

    longest_lookback_ready_idx = params.momentum_skip + max(params.momentum_lookbacks)
    assert not pd.isna(score.iloc[longest_lookback_ready_idx])


def test_momentum_score_penalizes_volatility(dates, params):
    """Equal drift, different vol: the lower-vol series must score higher
    after vol-adjustment, even though raw returns are similar."""
    steady = trending_series(dates, annual_drift=0.18, annual_vol=0.10, seed=1)
    volatile = trending_series(dates, annual_drift=0.18, annual_vol=0.35, seed=2)

    assert momentum_score(steady, params).iloc[-1] > momentum_score(volatile, params).iloc[-1]
