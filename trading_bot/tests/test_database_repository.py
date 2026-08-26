from datetime import datetime, timedelta

import pytest

from app.broker.models import BrokerPosition, Fill, Order, OrderRequest, OrderSide, OrderStatus
from app.database import repository
from app.database.session import create_db_engine, make_session_factory


@pytest.fixture
def session():
    engine = create_db_engine("sqlite:///:memory:")
    factory = make_session_factory(engine)
    with factory() as s:
        yield s


def test_replace_all_positions_overwrites_previous_state(session):
    now = datetime(2024, 1, 2, 9, 30)
    repository.replace_all_positions(session, {"AAA": BrokerPosition("AAA", 10, 100.0)}, now)
    repository.replace_all_positions(session, {"BBB": BrokerPosition("BBB", 5, 50.0)}, now)

    positions = repository.get_all_positions(session)

    assert set(positions.keys()) == {"BBB"}
    assert positions["BBB"].qty == 5


def test_replace_all_positions_with_empty_dict_clears_table(session):
    now = datetime(2024, 1, 2, 9, 30)
    repository.replace_all_positions(session, {"AAA": BrokerPosition("AAA", 10, 100.0)}, now)
    repository.replace_all_positions(session, {}, now)

    assert repository.get_all_positions(session) == {}


def test_upsert_order_inserts_new_and_updates_existing(session):
    now = datetime(2024, 1, 2, 9, 30)
    request = OrderRequest("AAA", OrderSide.BUY, 10)
    order = Order(id="order-1", request=request, status=OrderStatus.NEW, submitted_at=now)

    repository.upsert_order(session, order, now)
    stored = repository.get_open_orders(session)
    assert len(stored) == 1
    assert stored[0].status == "new"

    order.fills.append(Fill(qty=10, price=100.0, timestamp=now))
    order.status = OrderStatus.FILLED
    repository.upsert_order(session, order, now)

    assert repository.get_open_orders(session) == []  # no longer open


def test_get_open_orders_excludes_terminal_statuses(session):
    now = datetime(2024, 1, 2, 9, 30)
    for i, status in enumerate([OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED,
                                 OrderStatus.REJECTED, OrderStatus.CANCELED]):
        order = Order(id=f"o{i}", request=OrderRequest("AAA", OrderSide.BUY, 1), status=status, submitted_at=now)
        repository.upsert_order(session, order, now)

    open_ids = {o.id for o in repository.get_open_orders(session)}
    assert open_ids == {"o0", "o1"}


def test_equity_snapshot_day_start_is_first_snapshot_of_the_day(session):
    day1_morning = datetime(2024, 1, 2, 9, 30)
    day1_afternoon = datetime(2024, 1, 2, 15, 0)

    repository.record_equity_snapshot(session, day1_morning, equity=100_000, cash=100_000)
    repository.record_equity_snapshot(session, day1_afternoon, equity=101_000, cash=101_000)

    assert repository.get_day_start_equity(session, day1_afternoon) == 100_000


def test_equity_snapshot_day_start_resets_on_a_new_day(session):
    day1 = datetime(2024, 1, 2, 9, 30)
    day2 = datetime(2024, 1, 3, 9, 30)

    repository.record_equity_snapshot(session, day1, equity=100_000, cash=100_000)
    repository.record_equity_snapshot(session, day2, equity=95_000, cash=95_000)

    assert repository.get_day_start_equity(session, day2) == 95_000


def test_get_week_start_equity_uses_first_snapshot_since_monday(session):
    monday = datetime(2024, 1, 1, 9, 30)  # a Monday
    wednesday = datetime(2024, 1, 3, 9, 30)
    friday = datetime(2024, 1, 5, 15, 0)

    repository.record_equity_snapshot(session, monday, equity=100_000, cash=100_000)
    repository.record_equity_snapshot(session, wednesday, equity=99_000, cash=99_000)
    repository.record_equity_snapshot(session, friday, equity=98_000, cash=98_000)

    assert repository.get_week_start_equity(session, friday) == 100_000


def test_get_week_start_equity_resets_on_a_new_week(session):
    monday_week1 = datetime(2024, 1, 1, 9, 30)
    monday_week2 = datetime(2024, 1, 8, 9, 30)

    repository.record_equity_snapshot(session, monday_week1, equity=100_000, cash=100_000)
    repository.record_equity_snapshot(session, monday_week2, equity=102_000, cash=102_000)

    assert repository.get_week_start_equity(session, monday_week2) == 102_000


def test_get_peak_equity_is_the_max_ever_recorded(session):
    now = datetime(2024, 1, 2, 9, 30)
    for equity in [100_000, 120_000, 90_000, 110_000]:
        repository.record_equity_snapshot(session, now, equity=equity, cash=equity)

    assert repository.get_peak_equity(session) == 120_000


def test_no_equity_history_returns_none(session):
    now = datetime(2024, 1, 2, 9, 30)
    assert repository.get_day_start_equity(session, now) is None
    assert repository.get_week_start_equity(session, now) is None
    assert repository.get_peak_equity(session) is None
