"""Stage 10 failure testing: duplicate orders. Target weights/deltas are
computed from the broker's current positions, which don't yet reflect an
order that's accepted but not filled. Rerunning a rebalance cycle before
the previous one's orders resolve -- e.g. after a crash-restart replay, or
a scheduler double-fire -- would otherwise recompute the identical delta
and submit a duplicate order on top of the first. TradingEngine now
refuses to submit new orders while any are still open; these tests prove
that guard actually blocks the resubmission, alerts about it, and lifts
once the orders resolve.
"""
from datetime import datetime, timedelta

import pandas as pd
import pytest

from app.alerts.manager import AlertManager
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


class RecordingSink:
    def __init__(self):
        self.events = []

    def send(self, event):
        self.events.append(event)
        return True


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


@pytest.fixture
def current_prices(price_history):
    latest = price_history.iloc[-1]
    return {sym: float(latest[sym]) for sym in price_history.columns}


@pytest.fixture
def engine(session, price_history, current_prices):
    # Non-zero latency: orders stay open (NEW) after submission instead of
    # filling immediately, so a second cycle genuinely sees them as open.
    from app.broker.latency import FixedLatency

    broker = PaperBroker(
        starting_cash=100_000.0,
        price_lookup=lambda s: current_prices.get(s),
        slippage_model=FixedBpsSlippage(bps=0),
        latency_model=FixedLatency(seconds=300),
    )
    params = StrategyParams(top_k=1, rank_buffer=1, defensive_asset="SHY")
    risk_engine = RiskEngine(RiskLimits(max_position_pct=1.0))
    sink = RecordingSink()
    eng = TradingEngine(
        broker=broker, session=session, risk_engine=risk_engine,
        strategy_params=params, price_lookup=lambda s: current_prices.get(s),
        alert_manager=AlertManager([sink]),
    )
    eng.reconcile_on_startup(price_history.index[-1].to_pydatetime())
    return eng, broker, sink


def test_second_cycle_before_fills_submits_nothing_new(engine, price_history, current_prices, now):
    eng, broker, sink = engine

    first = eng.run_rebalance_cycle(now, price_history, current_prices)
    assert len(first.submitted_orders) > 0  # sanity: the first cycle actually traded
    assert first.skipped_reason is None

    second = eng.run_rebalance_cycle(now, price_history, current_prices)

    assert second.submitted_orders == []
    assert second.proposed_orders == []
    assert second.skipped_reason is not None


def test_duplicate_guard_does_not_double_the_broker_position(engine, price_history, current_prices, now):
    eng, broker, sink = engine

    eng.run_rebalance_cycle(now, price_history, current_prices)
    orders_after_first = broker.list_orders(since=now - timedelta(days=1))

    eng.run_rebalance_cycle(now, price_history, current_prices)
    orders_after_second = broker.list_orders(since=now - timedelta(days=1))

    assert len(orders_after_second) == len(orders_after_first)  # no new order was created


def test_duplicate_guard_fires_a_warning_alert(engine, price_history, current_prices, now):
    eng, broker, sink = engine

    eng.run_rebalance_cycle(now, price_history, current_prices)
    assert sink.events == []  # first cycle: nothing to warn about

    eng.run_rebalance_cycle(now, price_history, current_prices)

    assert len(sink.events) == 1
    assert sink.events[0].severity.value == "WARNING"
    assert "open" in sink.events[0].detail.lower()


def test_cycle_proceeds_again_once_open_orders_resolve(engine, price_history, current_prices, now):
    eng, broker, sink = engine

    eng.run_rebalance_cycle(now, price_history, current_prices)
    second = eng.run_rebalance_cycle(now, price_history, current_prices)
    assert second.skipped_reason is not None  # blocked, as proven above

    later = now + timedelta(minutes=10)
    eng.poll_fills(later)  # latency elapses -- order fills, and the DB record is updated

    third = eng.run_rebalance_cycle(later, price_history, current_prices)
    assert third.skipped_reason is None
