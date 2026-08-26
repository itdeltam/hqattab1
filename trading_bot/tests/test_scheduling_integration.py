"""End-to-end integration: TradingScheduler driving a real TradingEngine
and PaperBroker (not fakes) -- proves the full
scheduler -> engine -> strategy -> risk -> broker pipeline actually works
when invoked the way app/main.py's run() drives it, not just that each
piece behaves correctly in isolation.
"""
from datetime import datetime, timedelta

import pandas as pd
import pytest

from app.backtesting.costs import FixedBpsSlippage
from app.broker.paper import PaperBroker
from app.database.session import create_db_engine, make_session_factory
from app.market_data.live_price_cache import LivePriceCache
from app.market_data.synthetic import trending_series
from app.risk.engine import RiskEngine
from app.risk.limits import RiskLimits
from app.scheduling import TradingScheduler
from app.strategy.params import StrategyParams
from app.trading_engine import TradingEngine

SPECS = {
    "UP": dict(annual_drift=0.25, annual_vol=0.12, seed=1),
    "DOWN": dict(annual_drift=-0.20, annual_vol=0.15, seed=2),
    "SHY": dict(annual_drift=0.02, annual_vol=0.02, seed=3),
}
REBALANCE_DAY = datetime(2024, 1, 2, 9, 35)  # first NYSE session of Jan 2024


class StubMarketData:
    """Stands in for AlpacaMarketData -- same two-method shape, serving
    pre-built synthetic data instead of a real network call."""

    def __init__(self, price_history: pd.DataFrame, current_prices: dict[str, float]):
        self._price_history = price_history
        self._current_prices = current_prices

    def get_daily_close_history(self, symbols, start, end):
        return self._price_history[symbols]

    def get_latest_prices(self, symbols):
        return {s: self._current_prices[s] for s in symbols}


@pytest.fixture
def price_history():
    dates = pd.bdate_range(end=REBALANCE_DAY - timedelta(days=1), periods=400)
    return pd.DataFrame({
        sym: trending_series(dates, p["annual_drift"], p["annual_vol"], seed=p["seed"])
        for sym, p in SPECS.items()
    })


@pytest.fixture
def current_prices(price_history):
    latest = price_history.iloc[-1]
    return {sym: float(latest[sym]) for sym in price_history.columns}


def test_scheduler_run_rebalance_drives_a_real_engine_to_submit_orders(price_history, current_prices):
    session = make_session_factory(create_db_engine("sqlite:///:memory:"))()
    price_cache = LivePriceCache()
    broker = PaperBroker(
        starting_cash=100_000.0,
        price_lookup=price_cache.get,
        slippage_model=FixedBpsSlippage(bps=0),
    )
    engine = TradingEngine(
        broker=broker, session=session,
        risk_engine=RiskEngine(RiskLimits(max_position_pct=1.0)),
        strategy_params=StrategyParams(top_k=1, rank_buffer=1, defensive_asset="SHY"),
        price_lookup=price_cache.get,
    )
    engine.reconcile_on_startup(REBALANCE_DAY)

    scheduler = TradingScheduler(
        engine=engine,
        market_data=StubMarketData(price_history, current_prices),
        price_cache=price_cache,
        universe=tuple(price_history.columns),
    )

    result = scheduler.run_rebalance(REBALANCE_DAY)

    assert result is not None
    assert len(result.submitted_orders) > 0
    assert any(o.request.symbol == "UP" for o in result.submitted_orders)

    engine.poll_fills(REBALANCE_DAY)  # zero-latency default broker -> fills immediately
    assert broker.get_positions()  # something actually landed on the broker
