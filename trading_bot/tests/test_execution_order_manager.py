from datetime import datetime, timedelta

import pytest

from app.backtesting.costs import FixedBpsSlippage
from app.broker.latency import FixedLatency
from app.broker.paper import PaperBroker
from app.database import repository
from app.database.session import create_db_engine, make_session_factory
from app.execution.order_manager import OrderManager
from app.risk.models import ProposedOrder

NOW = datetime(2024, 1, 2, 9, 30)


@pytest.fixture
def session():
    engine = create_db_engine("sqlite:///:memory:")
    factory = make_session_factory(engine)
    with factory() as s:
        yield s


@pytest.fixture
def prices():
    return {"AAA": 100.0, "BBB": 50.0}


def make_broker(prices, **kwargs):
    kwargs.setdefault("slippage_model", FixedBpsSlippage(bps=0))
    return PaperBroker(starting_cash=100_000.0, price_lookup=lambda s: prices.get(s), **kwargs)


def test_submitting_approved_orders_persists_them_to_db(session, prices):
    broker = make_broker(prices)
    manager = OrderManager(broker, session)
    orders = [
        ProposedOrder(symbol="AAA", side="buy", shares=10, price=100.0),
        ProposedOrder(symbol="BBB", side="buy", shares=5, price=50.0),
    ]

    submitted = manager.submit_approved_orders(orders, now=NOW)

    assert len(submitted) == 2
    open_orders = repository.get_open_orders(session)
    assert {o.symbol for o in open_orders} == {"AAA", "BBB"}


def test_rejected_order_is_recorded_but_never_retried(session, prices):
    broker = make_broker(prices)
    broker.cash = 10.0  # too little cash for the order below
    manager = OrderManager(broker, session)
    orders = [ProposedOrder(symbol="AAA", side="buy", shares=10, price=100.0)]

    submitted = manager.submit_approved_orders(orders, now=NOW)

    assert submitted[0].status.value == "rejected"
    assert repository.get_open_orders(session) == []  # not open, and never resubmitted

    # Calling submit again with an empty list (simulating the next cycle
    # deciding not to retry) leaves the rejected order as the only record.
    manager.submit_approved_orders([], now=NOW)
    assert repository.get_open_orders(session) == []


def test_poll_fills_advances_broker_and_syncs_db(session, prices):
    broker = make_broker(prices, latency_model=FixedLatency(seconds=60))
    manager = OrderManager(broker, session)
    manager.submit_approved_orders([ProposedOrder(symbol="AAA", side="buy", shares=10, price=100.0)], now=NOW)

    assert len(repository.get_open_orders(session)) == 1  # still pending, latency not elapsed

    updated = manager.poll_fills(NOW + timedelta(seconds=60))

    assert len(updated) == 1
    assert updated[0].status.value == "filled"
    assert repository.get_open_orders(session) == []


def test_poll_fills_with_nothing_pending_returns_empty_list(session, prices):
    broker = make_broker(prices)
    manager = OrderManager(broker, session)

    assert manager.poll_fills(NOW) == []
