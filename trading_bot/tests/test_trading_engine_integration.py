"""End-to-end integration test for Stage 6: the full
Strategy -> Portfolio -> Risk Engine -> Order Manager -> Broker pipeline,
with startup reconciliation running first. Each piece already has its own
unit tests in isolation; this proves they're wired together correctly and
in the right order.
"""
from datetime import datetime, timedelta

import pandas as pd
import pytest

from app.alerts.events import Severity
from app.alerts.manager import AlertManager
from app.backtesting.costs import FixedBpsSlippage
from app.broker.paper import PaperBroker
from app.database.models import PositionRecord
from app.database.session import create_db_engine, make_session_factory
from app.market_data.synthetic import trending_series
from app.monitoring.heartbeat import get_heartbeat
from app.risk.engine import RiskEngine
from app.risk.limits import RiskLimits
from app.strategy.params import StrategyParams
from app.trading_engine import TradingEngine


class RecordingSink:
    def __init__(self):
        self.events = []

    def send(self, event):
        self.events.append(event)
        return True

SPECS = {
    "UP": dict(annual_drift=0.25, annual_vol=0.12, seed=1),
    "DOWN": dict(annual_drift=-0.20, annual_vol=0.15, seed=2),
    "SHY": dict(annual_drift=0.02, annual_vol=0.02, seed=3),
}


@pytest.fixture
def session():
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


def make_engine(session, price_history, current_prices, limits=None, starting_cash=100_000.0, alert_manager=None):
    broker = PaperBroker(
        starting_cash=starting_cash,
        price_lookup=lambda s: current_prices.get(s),
        slippage_model=FixedBpsSlippage(bps=0),
    )
    params = StrategyParams(top_k=1, rank_buffer=1, defensive_asset="SHY")
    risk_engine = RiskEngine(limits or RiskLimits(max_position_pct=1.0))
    kwargs = {}
    if alert_manager is not None:
        kwargs["alert_manager"] = alert_manager
    return TradingEngine(
        broker=broker, session=session, risk_engine=risk_engine,
        strategy_params=params, price_lookup=lambda s: current_prices.get(s),
        **kwargs,
    ), broker


def test_reconciliation_runs_before_trading_and_corrects_stale_state(session, price_history, current_prices, now):
    engine, broker = make_engine(session, price_history, current_prices)

    # Seed the DB with wrong/stale state, as if from a previous crashed run.
    session.add(PositionRecord(symbol="GHOST", qty=500, avg_entry_price=1.0, updated_at=now))
    session.commit()

    report = engine.reconcile_on_startup(now)

    assert not report.is_clean
    assert any("GHOST" in d for d in report.discrepancies)
    assert report.positions_after == {}  # broker had nothing -- DB now matches


def test_full_cycle_selects_uptrend_and_avoids_downtrend(session, price_history, current_prices, now):
    engine, broker = make_engine(session, price_history, current_prices)
    engine.reconcile_on_startup(now)

    result = engine.run_rebalance_cycle(now, price_history, current_prices)

    assert "UP" in result.selected
    assert "DOWN" not in result.selected
    assert any(o.request.symbol == "UP" and o.request.side.value == "buy" for o in result.submitted_orders)
    assert all(o.request.symbol != "DOWN" for o in result.submitted_orders)


def test_no_order_reaches_the_broker_without_passing_risk_engine(session, price_history, current_prices, now):
    # A zero position cap leaves no headroom at all, so every proposed buy
    # is fully vetoed (not merely clipped) -- proving there's no path
    # around the Risk Engine in this pipeline.
    tight_limits = RiskLimits(max_position_pct=0.0)
    engine, broker = make_engine(session, price_history, current_prices, limits=tight_limits)
    engine.reconcile_on_startup(now)

    result = engine.run_rebalance_cycle(now, price_history, current_prices)

    assert len(result.proposed_orders) > 0  # the strategy did propose trades
    assert result.submitted_orders == []  # but none reached the broker
    assert len(result.risk_decision.vetoed_orders) == len(result.proposed_orders)
    assert broker.get_positions() == {}


def test_fills_resolve_and_next_cycle_sees_updated_broker_positions(session, price_history, current_prices, now):
    engine, broker = make_engine(session, price_history, current_prices)
    engine.reconcile_on_startup(now)

    result = engine.run_rebalance_cycle(now, price_history, current_prices)
    assert len(result.submitted_orders) > 0

    engine.poll_fills(now)  # zero-latency default broker -> fills immediately

    positions = broker.get_positions()
    assert "UP" in positions
    assert positions["UP"].qty > 0


def test_second_cycle_respects_buffer_using_actual_broker_holdings_not_a_separate_ledger(
    session, price_history, current_prices, now,
):
    """current_momentum_holdings is derived from broker.get_positions(),
    not a separately tracked set -- this proves that derivation actually
    round-trips correctly through a real submit+fill+re-read cycle."""
    engine, broker = make_engine(session, price_history, current_prices)
    engine.reconcile_on_startup(now)

    engine.run_rebalance_cycle(now, price_history, current_prices)
    engine.poll_fills(now)

    second_result = engine.run_rebalance_cycle(now, price_history, current_prices)

    # UP is already held and still the top-ranked eligible asset -- the
    # second cycle should not need to re-buy from scratch (no large delta),
    # i.e. it should either propose nothing for UP or a small rebalancing
    # nudge, never a fresh full-size buy identical to the first cycle.
    up_orders_second_cycle = [o for o in second_result.proposed_orders if o.symbol == "UP"]
    assert up_orders_second_cycle == [] or up_orders_second_cycle[0].shares < 1.0


def test_equity_snapshot_recorded_on_every_cycle(session, price_history, current_prices, now):
    engine, broker = make_engine(session, price_history, current_prices)
    engine.reconcile_on_startup(now)

    from app.database import repository
    engine.run_rebalance_cycle(now, price_history, current_prices)

    assert repository.get_day_start_equity(session, now) == pytest.approx(100_000.0)


def test_reconciliation_discrepancy_triggers_an_alert(session, price_history, current_prices, now):
    sink = RecordingSink()
    engine, broker = make_engine(session, price_history, current_prices, alert_manager=AlertManager([sink]))

    # Seed the DB with stale state the broker knows nothing about.
    session.add(PositionRecord(symbol="GHOST", qty=500, avg_entry_price=1.0, updated_at=now))
    session.commit()

    engine.reconcile_on_startup(now)

    assert len(sink.events) == 1
    assert sink.events[0].severity == Severity.WARNING
    assert "GHOST" in sink.events[0].detail


def test_clean_reconciliation_does_not_alert(session, price_history, current_prices, now):
    sink = RecordingSink()
    engine, broker = make_engine(session, price_history, current_prices, alert_manager=AlertManager([sink]))

    engine.reconcile_on_startup(now)

    assert sink.events == []


def test_heartbeat_recorded_on_startup_and_every_rebalance_cycle(session, price_history, current_prices, now):
    engine, broker = make_engine(session, price_history, current_prices)

    engine.reconcile_on_startup(now)
    assert get_heartbeat(session, "trading_engine").last_beat_at == now

    later = now + timedelta(minutes=5)
    engine.run_rebalance_cycle(later, price_history, current_prices)
    assert get_heartbeat(session, "trading_engine").last_beat_at == later
