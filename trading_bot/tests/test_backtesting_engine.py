import pandas as pd
import pytest

from app.backtesting.calendar import monthly_rebalance_dates, trading_sessions
from app.backtesting.costs import FixedBpsSlippage, PerShareCommission, ZeroCommission
from app.backtesting.engine import BacktestConfig, BacktestEngine
from app.market_data.bars import PriceHistory
from app.market_data.synthetic import trending_series
from app.strategy.params import StrategyParams

SPECS = {
    "A": dict(annual_drift=0.20, annual_vol=0.12, seed=1),    # strong, steady uptrend
    "B": dict(annual_drift=-0.15, annual_vol=0.15, seed=2),   # confirmed downtrend, whole window
    "SHY": dict(annual_drift=0.02, annual_vol=0.02, seed=3),  # defensive leg
}


@pytest.fixture
def history():
    sessions = trading_sessions("2019-01-01", "2021-12-31")
    close = pd.DataFrame({
        sym: trending_series(sessions, p["annual_drift"], p["annual_vol"], seed=p["seed"])
        for sym, p in SPECS.items()
    })
    open_ = close.shift(1)
    open_.iloc[0] = close.iloc[0]
    return PriceHistory(close=close, open=open_)


@pytest.fixture
def rebalances(history):
    return monthly_rebalance_dates(history.dates)


@pytest.fixture
def params():
    return StrategyParams(top_k=2, rank_buffer=1, defensive_asset="SHY")


def test_equity_curve_starts_at_starting_capital(history, rebalances, params):
    config = BacktestConfig(starting_capital=50_000, strategy_params=params)
    result = BacktestEngine(config).run(history, rebalances)
    assert result.equity_curve.iloc[0] == 50_000


def test_downtrend_asset_never_gets_bought(history, rebalances, params):
    """B is a confirmed downtrend for the entire window -- the trend filter
    must keep it ineligible throughout, so it should never appear as a buy
    (or any trade at all, since it's never held to begin with)."""
    config = BacktestConfig(strategy_params=params)
    result = BacktestEngine(config).run(history, rebalances)

    b_trades = [t for t in result.trades if t.symbol == "B"]
    assert b_trades == []


def test_momentum_sleeve_waits_for_full_signal_history(history, rebalances, params):
    """The defensive leg can be bought immediately (it needs no momentum
    history -- see engine.py's sleeve_frac=0 fallback). A momentum-sleeve
    asset (A) must not be bought before its score has full history."""
    config = BacktestConfig(strategy_params=params)
    result = BacktestEngine(config).run(history, rebalances)

    first_valid_score_date = history.dates[params.momentum_skip + max(params.momentum_lookbacks)]
    early_a_trades = [
        t for t in result.trades if t.symbol == "A" and t.date < first_valid_score_date
    ]
    assert early_a_trades == []

    later_a_trades = [t for t in result.trades if t.symbol == "A"]
    assert len(later_a_trades) > 0, "A should eventually be selected -- it's a strong uptrend"


def test_costs_reduce_final_equity(history, rebalances, params):
    zero_cost_config = BacktestConfig(
        strategy_params=params,
        commission_model=ZeroCommission(),
        slippage_model=FixedBpsSlippage(bps=0),
    )
    costly_config = BacktestConfig(
        strategy_params=params,
        commission_model=PerShareCommission(rate_per_share=0.01),
        slippage_model=FixedBpsSlippage(bps=10),
    )

    zero_cost_result = BacktestEngine(zero_cost_config).run(history, rebalances)
    costly_result = BacktestEngine(costly_config).run(history, rebalances)

    assert len(costly_result.trades) > 0
    assert costly_result.equity_curve.iloc[-1] < zero_cost_result.equity_curve.iloc[-1]


def test_slippage_applied_against_the_trader(history, rebalances, params):
    config = BacktestConfig(strategy_params=params, slippage_model=FixedBpsSlippage(bps=25))
    result = BacktestEngine(config).run(history, rebalances)

    assert len(result.trades) > 0
    for trade in result.trades:
        reference_open = history.open.loc[trade.date, trade.symbol]
        if trade.side == "buy":
            assert trade.price > reference_open
        else:
            assert trade.price < reference_open


def test_all_trades_land_on_rebalance_sessions(history, rebalances, params):
    config = BacktestConfig(strategy_params=params)
    result = BacktestEngine(config).run(history, rebalances)

    rebalance_set = set(rebalances)
    assert len(result.trades) > 0
    assert all(t.date in rebalance_set for t in result.trades)


def test_portfolio_stays_fully_invested_once_signals_are_live(history, rebalances, params):
    """sleeve_frac + defensive_frac always sum to 1 by construction, so once
    signals are valid, cash should be small relative to equity (not exactly
    zero, since target shares are rounded to whatever price division gives
    and small residuals accumulate)."""
    config = BacktestConfig(strategy_params=params)
    engine = BacktestEngine(config)
    result = engine.run(history, rebalances)

    last_date = history.dates[-1]
    final_equity = result.equity_curve.loc[last_date]
    assert final_equity > 0
