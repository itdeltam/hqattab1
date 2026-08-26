"""The flagship test module for Stage 6's non-negotiable rule: 'on every
startup, reconcile local DB state against the broker's actual
account/positions/orders before allowing any trading. Broker state is
always authoritative.' These tests simulate a restart by keeping the same
broker instance (which holds the 'real' state) while deliberately seeding
the DB with stale/wrong/corrupted data, then proving reconcile always
makes the broker win.
"""
from datetime import datetime

import pytest

from app.broker.models import OrderRequest, OrderSide
from app.broker.paper import PaperBroker
from app.database import repository
from app.database.models import OrderRecord, PositionRecord
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
    prices = {"AAA": 100.0, "BBB": 50.0}
    return PaperBroker(starting_cash=100_000.0, price_lookup=lambda s: prices.get(s))


def test_reconcile_overwrites_stale_local_positions_with_broker_truth(session, broker):
    broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    broker.advance_time(NOW)  # broker truth: 10 shares of AAA

    # DB has stale/wrong data: thinks we hold 999 shares of AAA and 50 of a
    # symbol the broker has never even heard of.
    session.add(PositionRecord(symbol="AAA", qty=999, avg_entry_price=1.0, updated_at=NOW))
    session.add(PositionRecord(symbol="ZZZZ", qty=50, avg_entry_price=1.0, updated_at=NOW))
    session.commit()

    report = reconcile_startup_state(broker, session, NOW)

    positions = repository.get_all_positions(session)
    assert set(positions.keys()) == {"AAA"}
    assert positions["AAA"].qty == 10
    assert not report.is_clean
    assert any("AAA" in d for d in report.discrepancies)
    assert any("ZZZZ" in d for d in report.discrepancies)


def test_reconcile_is_clean_when_db_already_matches_broker(session, broker):
    broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    broker.advance_time(NOW)

    report_1 = reconcile_startup_state(broker, session, NOW)
    assert not report_1.is_clean  # first run: DB was empty, broker has a position

    report_2 = reconcile_startup_state(broker, session, NOW)
    assert report_2.is_clean
    assert report_2.discrepancies == []


def test_reconcile_updates_stale_order_status_from_broker(session, broker):
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    # DB still thinks the order is NEW, but the broker will show FILLED
    # once we advance time -- simulating a crash between submit and the
    # app recording the fill.
    session.add(OrderRecord(
        id=order.id, symbol="AAA", side="buy", qty=10, status="new",
        submitted_at=NOW, filled_qty=0.0, updated_at=NOW,
    ))
    session.commit()

    broker.advance_time(NOW)  # broker now shows this order as FILLED

    report = reconcile_startup_state(broker, session, NOW)

    open_orders = repository.get_open_orders(session)
    assert open_orders == []
    assert any("broker wins" in d for d in report.discrepancies)
    assert order.id in report.orders_resynced


def test_reconcile_handles_order_unknown_to_broker_without_crashing(session, broker):
    session.add(OrderRecord(
        id="ghost-order", symbol="AAA", side="buy", qty=10, status="new",
        submitted_at=NOW, filled_qty=0.0, updated_at=NOW,
    ))
    session.commit()

    report = reconcile_startup_state(broker, session, NOW)

    assert not report.is_clean
    assert any("ghost-order" in d for d in report.discrepancies)


def test_reconcile_records_an_equity_snapshot(session, broker):
    reconcile_startup_state(broker, session, NOW)

    assert repository.get_day_start_equity(session, NOW) == pytest.approx(100_000.0)


def test_reconcile_on_empty_db_and_empty_broker_is_clean(session, broker):
    report = reconcile_startup_state(broker, session, NOW)

    assert report.is_clean
    assert report.positions_after == {}
