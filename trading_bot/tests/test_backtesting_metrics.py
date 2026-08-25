import pandas as pd
import pytest

from app.backtesting.metrics import annualized_vol, cagr, max_drawdown, sharpe_ratio, total_return


def test_total_return_simple_doubling():
    equity = pd.Series([100.0, 150.0, 200.0])
    assert total_return(equity) == pytest.approx(1.0)


def test_cagr_matches_known_annualized_growth():
    # Exactly 2x over 252 trading days (1 year) -> CAGR should be 100%.
    equity = pd.Series([100.0] + [100.0 * (2 ** (i / 252)) for i in range(1, 253)])
    assert cagr(equity, periods_per_year=252) == pytest.approx(1.0, rel=1e-6)


def test_cagr_zero_length_is_zero():
    equity = pd.Series([100.0])
    assert cagr(equity) == 0.0


def test_max_drawdown_detects_known_drop():
    equity = pd.Series([100.0, 120.0, 60.0, 90.0])
    # peak 120 -> trough 60 is a 50% drawdown.
    assert max_drawdown(equity) == pytest.approx(-0.5)


def test_max_drawdown_is_zero_for_monotonic_increase():
    equity = pd.Series([100.0, 110.0, 120.0])
    assert max_drawdown(equity) == pytest.approx(0.0)


def test_annualized_vol_of_constant_equity_is_zero():
    equity = pd.Series([100.0] * 30)
    assert annualized_vol(equity) == 0.0


def test_sharpe_ratio_zero_vol_returns_zero_not_error():
    equity = pd.Series([100.0] * 30)
    assert sharpe_ratio(equity) == 0.0


def test_sharpe_ratio_positive_for_steady_gains():
    equity = pd.Series([100.0 * (1.001 ** i) for i in range(100)])
    assert sharpe_ratio(equity) > 0
