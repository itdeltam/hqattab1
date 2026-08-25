from datetime import datetime, timedelta

import pytest

from app.database.models import OrderRecord, PositionRecord
from app.database.repository import record_equity_snapshot
from app.database.session import create_db_engine, make_session_factory
from app.monitoring.heartbeat import record_heartbeat
from app.web.data import get_account_summary, get_positions_view, get_recent_orders, get_system_status

NOW = datetime(2024, 1, 2, 9, 30)


@pytest.fixture
def session():
    engine = create_db_engine("sqlite:///:memory:")
    factory = make_session_factory(engine)
    with factory() as s:
        yield s


def test_account_summary_empty_db_has_no_data(session):
    summary = get_account_summary(session)
    assert summary.has_data is False
    assert summary.equity is None


def test_account_summary_returns_latest_snapshot(session):
    record_equity_snapshot(session, NOW, equity=100_000, cash=100_000)
    record_equity_snapshot(session, NOW + timedelta(hours=1), equity=101_000, cash=90_000)

    summary = get_account_summary(session)

    assert summary.has_data is True
    assert summary.equity == 101_000
    assert summary.cash == 90_000
    assert summary.as_of == NOW + timedelta(hours=1)


def test_positions_view_empty_when_no_positions(session):
    assert get_positions_view(session) == []


def test_positions_view_computes_cost_basis_and_sorts_by_symbol(session):
    session.add(PositionRecord(symbol="BBB", qty=5, avg_entry_price=50.0, updated_at=NOW))
    session.add(PositionRecord(symbol="AAA", qty=10, avg_entry_price=100.0, updated_at=NOW))
    session.commit()

    views = get_positions_view(session)

    assert [v.symbol for v in views] == ["AAA", "BBB"]
    assert views[0].cost_basis == pytest.approx(1000.0)
    assert views[1].cost_basis == pytest.approx(250.0)


def test_recent_orders_returns_most_recent_first_and_respects_limit(session):
    for i in range(5):
        session.add(OrderRecord(
            id=f"o{i}", symbol="AAA", side="buy", qty=1, status="filled",
            submitted_at=NOW + timedelta(minutes=i), filled_qty=1, updated_at=NOW,
        ))
    session.commit()

    orders = get_recent_orders(session, limit=3)

    assert len(orders) == 3
    assert orders[0].id == "o4"  # most recent submitted_at first


def test_system_status_no_activity_yet(session):
    status = get_system_status(session, trading_mode="PAPER", now=NOW)

    assert status.trading_mode == "PAPER"
    assert status.last_activity is None
    assert status.seconds_since_activity is None
    assert status.last_heartbeat is None
    assert status.heartbeat_healthy is False


def test_system_status_reflects_most_recent_of_equity_or_order_activity(session):
    record_equity_snapshot(session, NOW, equity=100_000, cash=100_000)
    session.add(OrderRecord(
        id="o1", symbol="AAA", side="buy", qty=1, status="filled",
        submitted_at=NOW, filled_qty=1, updated_at=NOW + timedelta(minutes=10),
    ))
    session.commit()

    check_time = NOW + timedelta(minutes=15)
    status = get_system_status(session, trading_mode="PAPER", now=check_time)

    assert status.last_activity == NOW + timedelta(minutes=10)
    assert status.seconds_since_activity == pytest.approx(300.0)


def test_system_status_heartbeat_healthy_within_threshold(session):
    record_heartbeat(session, "trading_engine", NOW)

    status = get_system_status(session, "PAPER", NOW + timedelta(seconds=30), heartbeat_stale_seconds=120)

    assert status.last_heartbeat == NOW
    assert status.heartbeat_healthy is True


def test_system_status_heartbeat_stale_past_threshold(session):
    record_heartbeat(session, "trading_engine", NOW)

    status = get_system_status(session, "PAPER", NOW + timedelta(seconds=300), heartbeat_stale_seconds=120)

    assert status.last_heartbeat == NOW
    assert status.heartbeat_healthy is False
