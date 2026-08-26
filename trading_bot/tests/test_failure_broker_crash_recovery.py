"""Stage 10 failure testing: 'kill the connection mid-order.' The
dangerous window isn't just a submit() call that raises -- it's the gap
between broker.submit_order() succeeding and the local DB write that
would have recorded it. If the process dies in that exact gap (killed,
crashed, power loss), the local DB has zero record the order ever
happened, even though it's sitting on the broker's books. Position
reconciliation already self-heals from this (broker positions always
win), but the order audit trail would otherwise be lost forever.
reconcile_startup_state() now also recovers these via broker.list_orders().
"""
from datetime import datetime, timedelta

import pytest

from app.broker.models import OrderRequest, OrderSide
from app.broker.paper import PaperBroker
from app.database import repository
from app.database.reconciliation import reconcile_startup_state
from app.database.session import create_db_engine, make_session_factory

NOW = datetime(2024, 1, 2, 9, 30)


@pytest.fixture
def session():
    engine = create_db_engine("sqlite:///:memory:")
    factory = make_session_factory(engine)
    with factory() as s:
        yield s


@pytest.fixture
def broker():
    prices = {"AAA": 100.0}
    return PaperBroker(starting_cash=100_000.0, price_lookup=lambda s: prices.get(s))


def test_reconcile_recovers_an_order_the_broker_has_but_the_db_never_learned_about(session, broker):
    # Simulate: broker.submit_order() succeeded, then the process died
    # before app.database.repository.upsert_order() ever ran. The DB has
    # literally never heard of this order.
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    broker.advance_time(NOW)
    assert repository.get_all_order_ids(session) == set()  # confirm the gap

    report = reconcile_startup_state(broker, session, NOW)

    assert order.id in report.orders_recovered
    assert any("recovered" in d for d in report.discrepancies)
    assert not report.is_clean
    recovered_ids = repository.get_all_order_ids(session)
    assert order.id in recovered_ids


def test_recovered_order_has_correct_status_and_fill_data(session, broker):
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    broker.advance_time(NOW)  # fills immediately (zero latency default)

    reconcile_startup_state(broker, session, NOW)

    open_orders = repository.get_open_orders(session)
    assert open_orders == []  # recovered as FILLED, not stuck open forever
    all_ids = repository.get_all_order_ids(session)
    assert order.id in all_ids


def test_recovery_is_idempotent_second_reconcile_finds_nothing_new(session, broker):
    broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    broker.advance_time(NOW)

    reconcile_startup_state(broker, session, NOW)
    report_2 = reconcile_startup_state(broker, session, NOW)

    assert report_2.orders_recovered == []
    assert report_2.is_clean


def test_orders_already_known_to_the_db_are_not_recovered_again(session, broker):
    """An order the open-orders resync loop already handled must not also
    show up as 'recovered' -- that would double-count it and duplicate
    the discrepancy noise for the same underlying event."""
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    from app.database.models import OrderRecord
    session.add(OrderRecord(
        id=order.id, symbol="AAA", side="buy", qty=10, status="new",
        submitted_at=NOW, filled_qty=0.0, updated_at=NOW,
    ))
    session.commit()
    broker.advance_time(NOW)

    report = reconcile_startup_state(broker, session, NOW)

    assert order.id not in report.orders_recovered
    assert order.id in report.orders_resynced


def test_recovery_respects_the_lookback_window(session, broker):
    """An order submitted well outside the recovery lookback window should
    not suddenly reappear years later -- the window exists precisely so
    this doesn't scan unbounded account history on every startup."""
    old_time = NOW - timedelta(days=30)
    broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=old_time)
    broker.advance_time(old_time)

    report = reconcile_startup_state(broker, session, NOW)

    assert report.orders_recovered == []
