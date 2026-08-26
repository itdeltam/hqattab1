from datetime import datetime, timedelta

import pytest

from app.backtesting.costs import FixedBpsSlippage
from app.broker.models import OrderRequest, OrderSide
from app.broker.paper import PaperBroker
from app.database import repository
from app.database.session import create_db_engine, make_session_factory
from app.portfolio.portfolio import Portfolio

NOW = datetime(2024, 1, 2, 9, 30)


@pytest.fixture
def session():
    engine = create_db_engine("sqlite:///:memory:")
    factory = make_session_factory(engine)
    with factory() as s:
        yield s


@pytest.fixture
def prices():
    return {"AAA": 100.0}


@pytest.fixture
def broker(prices):
    return PaperBroker(
        starting_cash=100_000.0,
        price_lookup=lambda s: prices.get(s),
        slippage_model=FixedBpsSlippage(bps=0),
    )


def test_current_state_reflects_broker_positions(session, broker, prices):
    broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    broker.advance_time(NOW)
    portfolio = Portfolio(broker, session, price_lookup=lambda s: prices.get(s))

    state = portfolio.current_state(NOW)

    assert state.positions["AAA"].shares == 10
    assert state.positions["AAA"].avg_cost == pytest.approx(100.0)
    assert state.positions["AAA"].current_price == pytest.approx(100.0)
    assert state.equity == pytest.approx(100_000.0)


def test_current_price_reflects_price_movement(session, broker, prices):
    broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    broker.advance_time(NOW)
    portfolio = Portfolio(broker, session, price_lookup=lambda s: prices.get(s))

    prices["AAA"] = 150.0
    state = portfolio.current_state(NOW)

    assert state.positions["AAA"].current_price == pytest.approx(150.0)
    assert state.equity == pytest.approx(100_000.0 - 1_000.0 + 1_500.0)


def test_first_ever_state_defaults_day_week_peak_to_current_equity(session, broker, prices):
    portfolio = Portfolio(broker, session, price_lookup=lambda s: prices.get(s))

    state = portfolio.current_state(NOW)

    assert state.day_start_equity == pytest.approx(100_000.0)
    assert state.week_start_equity == pytest.approx(100_000.0)
    assert state.peak_equity == pytest.approx(100_000.0)


def test_day_start_equity_uses_first_recorded_snapshot_of_the_day(session, broker, prices):
    portfolio = Portfolio(broker, session, price_lookup=lambda s: prices.get(s))
    portfolio.record_equity_snapshot(NOW)

    prices["AAA"] = 999.0  # irrelevant since no position -- equity unaffected
    later_today = NOW + timedelta(hours=2)

    state = portfolio.current_state(later_today)
    assert state.day_start_equity == pytest.approx(100_000.0)


def test_peak_equity_never_decreases_even_if_current_equity_is_lower(session, broker, prices):
    portfolio = Portfolio(broker, session, price_lookup=lambda s: prices.get(s))
    repository.record_equity_snapshot(session, NOW, equity=120_000, cash=120_000)

    # Broker's actual current equity (100,000) is below the historical peak.
    state = portfolio.current_state(NOW)

    assert state.peak_equity == pytest.approx(120_000.0)
    assert state.equity == pytest.approx(100_000.0)


def test_peak_equity_reflects_a_new_all_time_high_not_yet_recorded(session, broker, prices):
    portfolio = Portfolio(broker, session, price_lookup=lambda s: prices.get(s))
    repository.record_equity_snapshot(session, NOW, equity=90_000, cash=90_000)

    # Current broker equity (100,000) is a new high that hasn't been snapshotted yet.
    state = portfolio.current_state(NOW)

    assert state.peak_equity == pytest.approx(100_000.0)


def test_current_state_falls_back_to_avg_cost_when_price_lookup_returns_none(session, broker, prices):
    """Stage 10 failure testing: a stale/missing quote for a held symbol
    (price feed gap, delisted symbol, whatever) must never crash portfolio
    valuation or silently price the position at zero -- fall back to the
    known avg cost, which is always a defensible, non-fabricated number."""
    broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    broker.advance_time(NOW)

    portfolio = Portfolio(broker, session, price_lookup=lambda s: None)  # simulates a dead feed

    state = portfolio.current_state(NOW)

    assert state.positions["AAA"].current_price == pytest.approx(100.0)  # avg_entry_price fallback
    assert state.equity == pytest.approx(100_000.0)  # never becomes NaN/zero


def test_current_state_propagates_price_lookup_exceptions_instead_of_masking_them(session, broker):
    """A price feed that raises (bad data source, malformed response) is a
    different failure mode than one that legitimately has no data (returns
    None) -- it must propagate and crash the cycle (for Stage 8's watchdog
    to alert on and retry) rather than being silently swallowed into a
    fallback value that could hide a real data-integrity problem."""
    broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    broker.advance_time(NOW)

    def broken_price_lookup(symbol):
        raise ValueError("malformed market data response")

    portfolio = Portfolio(broker, session, price_lookup=broken_price_lookup)

    with pytest.raises(ValueError):
        portfolio.current_state(NOW)


def test_week_start_equity_uses_first_snapshot_since_monday(session, broker, prices):
    monday = datetime(2024, 1, 1, 9, 30)
    portfolio = Portfolio(broker, session, price_lookup=lambda s: prices.get(s))
    repository.record_equity_snapshot(session, monday, equity=95_000, cash=95_000)

    friday = datetime(2024, 1, 5, 9, 30)
    state = portfolio.current_state(friday)

    assert state.week_start_equity == pytest.approx(95_000.0)
