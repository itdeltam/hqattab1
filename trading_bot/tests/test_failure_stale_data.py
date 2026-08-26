"""Stage 10 failure testing: stale/missing market data. A live-quote feed
going dark for a cycle (network blip, exchange feed gap) must never crash
the rebalance loop or silently price an order at zero -- it should fall
back to the last known historical close, which is always a real, sane
number, and the cycle should complete normally.
"""
from datetime import datetime, timedelta

import pandas as pd
import pytest

from app.backtesting.costs import FixedBpsSlippage
from app.broker.paper import PaperBroker
from app.market_data.synthetic import trending_series
from app.risk.engine import RiskEngine
from app.risk.limits import RiskLimits
from app.strategy.params import StrategyParams
from app.trading_engine import TradingEngine

SPECS = {
    "UP": dict(annual_drift=0.25, annual_vol=0.12, seed=1),
    "DOWN": dict(annual_drift=-0.20, annual_vol=0.15, seed=2),
    "SHY": dict(annual_drift=0.02, annual_vol=0.02, seed=3),
}


@pytest.fixture
def session():
    from app.database.session import create_db_engine, make_session_factory

    engine = create_db_engine("sqlite:///:memory:")
    factory = make_session_factory(engine)
    with factory() as s:
        yield s


@pytest.fixture
def price_history():
    dates = pd.bdate_range("2020-01-01", periods=400)
    return pd.DataFrame({
        sym: trending_series(dates, p["annual_drift"], p["annual_vol"], seed=p["seed"])
        for sym, p in SPECS.items()
    })


@pytest.fixture
def now(price_history):
    return price_history.index[-1].to_pydatetime() + timedelta(hours=9, minutes=30)


def test_cycle_completes_when_the_live_quote_feed_is_entirely_dark(session, price_history, now):
    """current_prices={} simulates a live-quote provider returning nothing
    at all for this cycle. The engine's own broker still has its own
    reference price (a separate, unrelated price_lookup), so orders can
    still be submitted -- they must just be priced from the last known
    historical close, not crash on a missing dict key."""
    last_close = {sym: float(price_history[sym].iloc[-1]) for sym in price_history.columns}
    broker = PaperBroker(
        starting_cash=100_000.0,
        price_lookup=lambda s: last_close.get(s),  # broker's own feed still works
        slippage_model=FixedBpsSlippage(bps=0),
    )
    params = StrategyParams(top_k=1, rank_buffer=1, defensive_asset="SHY")
    risk_engine = RiskEngine(RiskLimits(max_position_pct=1.0))
    engine = TradingEngine(
        broker=broker, session=session, risk_engine=risk_engine,
        strategy_params=params, price_lookup=lambda s: last_close.get(s),
    )
    engine.reconcile_on_startup(now)

    result = engine.run_rebalance_cycle(now, price_history, current_prices={})

    assert result.skipped_reason is None
    assert len(result.proposed_orders) > 0
    for order in result.proposed_orders:
        assert order.price == pytest.approx(float(price_history.loc[price_history.index[-1], order.symbol]))
        assert order.price > 0
    assert len(result.submitted_orders) > 0  # the cycle actually traded, not silently no-opped


def test_cycle_completes_when_the_live_quote_feed_is_missing_just_one_symbol(session, price_history, now):
    last_close = {sym: float(price_history[sym].iloc[-1]) for sym in price_history.columns}
    broker = PaperBroker(
        starting_cash=100_000.0,
        price_lookup=lambda s: last_close.get(s),
        slippage_model=FixedBpsSlippage(bps=0),
    )
    params = StrategyParams(top_k=1, rank_buffer=1, defensive_asset="SHY")
    risk_engine = RiskEngine(RiskLimits(max_position_pct=1.0))
    engine = TradingEngine(
        broker=broker, session=session, risk_engine=risk_engine,
        strategy_params=params, price_lookup=lambda s: last_close.get(s),
    )
    engine.reconcile_on_startup(now)

    partial_quotes = {"DOWN": last_close["DOWN"], "SHY": last_close["SHY"]}  # "UP" missing
    result = engine.run_rebalance_cycle(now, price_history, current_prices=partial_quotes)

    assert result.skipped_reason is None
    up_orders = [o for o in result.proposed_orders if o.symbol == "UP"]
    assert len(up_orders) == 1
    assert up_orders[0].price == pytest.approx(last_close["UP"])
