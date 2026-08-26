"""AlpacaBroker tests. All against a FakeTradingClient -- no real network,
no real credentials -- implementing exactly the slice of alpaca-py's
TradingClient this adapter depends on (see AlpacaTradingClient Protocol in
app/broker/alpaca.py).
"""
import json
import types
import uuid
from datetime import datetime

import pytest
from alpaca.common.exceptions import APIError
from alpaca.trading.enums import OrderSide as AlpacaOrderSide
from alpaca.trading.enums import OrderStatus as AlpacaOrderStatus

from app.broker.alpaca import AlpacaBroker
from app.broker.models import OrderRequest, OrderSide, OrderStatus

NOW = datetime(2024, 1, 2, 9, 30)


def make_api_error(message="rejected by broker"):
    return APIError(json.dumps({"code": 40310000, "message": message}))


def fake_alpaca_order(
    id=None, symbol="AAPL", side=AlpacaOrderSide.BUY, qty="10", status=AlpacaOrderStatus.NEW,
    filled_qty="0", filled_avg_price=None, filled_at=None, submitted_at=NOW,
):
    return types.SimpleNamespace(
        id=id or uuid.uuid4(), symbol=symbol, side=side, qty=qty, status=status,
        filled_qty=filled_qty, filled_avg_price=filled_avg_price, filled_at=filled_at, submitted_at=submitted_at,
    )


def fake_position(symbol="AAPL", qty="10.5", avg_entry_price="150.25"):
    return types.SimpleNamespace(symbol=symbol, qty=qty, avg_entry_price=avg_entry_price)


def fake_account(cash="50000.00", equity="52000.00", buying_power="50000.00", account_number="ACC-123"):
    return types.SimpleNamespace(cash=cash, equity=equity, buying_power=buying_power, account_number=account_number)


class FakeTradingClient:
    def __init__(self):
        self.submit_order_result = None
        self.submit_order_exc = None
        self.orders_by_id: dict[str, object] = {}
        self.get_order_by_id_exc = None
        self.cancel_calls = []
        self.positions = []
        self.account = None
        self.list_orders_result = []
        self.get_orders_calls = []

    def submit_order(self, order_data):
        if self.submit_order_exc:
            raise self.submit_order_exc
        order = self.submit_order_result
        self.orders_by_id[str(order.id)] = order
        return order

    def get_order_by_id(self, order_id):
        if self.get_order_by_id_exc:
            raise self.get_order_by_id_exc
        return self.orders_by_id[str(order_id)]

    def cancel_order_by_id(self, order_id):
        self.cancel_calls.append(str(order_id))

    def get_all_positions(self):
        return self.positions

    def get_account(self):
        return self.account

    def get_orders(self, filter=None):
        self.get_orders_calls.append(filter)
        return self.list_orders_result


@pytest.fixture
def client():
    return FakeTradingClient()


@pytest.fixture
def broker(client):
    return AlpacaBroker(api_key="k", secret_key="s", base_url="https://paper-api.alpaca.markets", trading_client=client)


def test_submit_order_success_converts_and_caches(broker, client):
    order_id = uuid.uuid4()
    client.submit_order_result = fake_alpaca_order(id=order_id, status=AlpacaOrderStatus.NEW, qty="10")

    order = broker.submit_order(OrderRequest(symbol="AAPL", side=OrderSide.BUY, qty=10), NOW)

    assert order.id == str(order_id)
    assert order.status == OrderStatus.NEW
    assert order.request.symbol == "AAPL"
    assert order.request.qty == 10.0
    assert order.filled_qty == 0.0


def test_submit_order_api_error_returns_rejected_order_without_raising(broker, client):
    client.submit_order_exc = make_api_error("insufficient buying power")

    order = broker.submit_order(OrderRequest(symbol="AAPL", side=OrderSide.BUY, qty=10), NOW)

    assert order.status == OrderStatus.REJECTED
    assert "insufficient buying power" in order.rejection_reason


@pytest.mark.parametrize("exc", [
    ConnectionError("network down"),
    TimeoutError("timed out"),
    ValueError("unexpected"),
])
def test_submit_order_non_api_error_propagates_never_fabricates_rejection(broker, client, exc):
    """The flagship property: only Alpaca's own APIError (a definitive
    broker verdict) may be converted into a REJECTED order. Anything else
    -- a network failure, a timeout, a bug -- must propagate uncaught. We
    must never guess the order's fate when we simply failed to find out.
    """
    client.submit_order_exc = exc

    with pytest.raises(type(exc)):
        broker.submit_order(OrderRequest(symbol="AAPL", side=OrderSide.BUY, qty=10), NOW)


def test_get_order_known_converts_correctly(broker, client):
    order_id = uuid.uuid4()
    client.orders_by_id[str(order_id)] = fake_alpaca_order(
        id=order_id, status=AlpacaOrderStatus.FILLED, qty="10", filled_qty="10", filled_avg_price="151.5",
    )

    order = broker.get_order(str(order_id))

    assert order.status == OrderStatus.FILLED
    assert order.filled_qty == 10.0
    assert order.avg_fill_price == pytest.approx(151.5)


def test_get_order_unknown_translates_api_error_to_key_error(broker, client):
    client.get_order_by_id_exc = make_api_error("order does not exist")

    with pytest.raises(KeyError):
        broker.get_order("does-not-exist")


def test_advance_time_returns_only_orders_that_changed(broker, client):
    order_id = uuid.uuid4()
    client.submit_order_result = fake_alpaca_order(id=order_id, status=AlpacaOrderStatus.NEW, qty="10", filled_qty="0")
    broker.submit_order(OrderRequest(symbol="AAPL", side=OrderSide.BUY, qty=10), NOW)

    # Broker-side, the order is still exactly NEW/unfilled -- no change.
    client.orders_by_id[str(order_id)] = fake_alpaca_order(id=order_id, status=AlpacaOrderStatus.NEW, qty="10", filled_qty="0")
    assert broker.advance_time(NOW) == []

    # Now it's partially filled -- must be reported.
    client.orders_by_id[str(order_id)] = fake_alpaca_order(
        id=order_id, status=AlpacaOrderStatus.PARTIALLY_FILLED, qty="10", filled_qty="4", filled_avg_price="150.0",
    )
    updated = broker.advance_time(NOW)
    assert len(updated) == 1
    assert updated[0].status == OrderStatus.PARTIALLY_FILLED
    assert updated[0].filled_qty == 4.0


def test_advance_time_skips_orders_already_closed_locally(broker, client):
    order_id = uuid.uuid4()
    client.submit_order_result = fake_alpaca_order(
        id=order_id, status=AlpacaOrderStatus.FILLED, qty="10", filled_qty="10", filled_avg_price="150.0",
    )
    broker.submit_order(OrderRequest(symbol="AAPL", side=OrderSide.BUY, qty=10), NOW)

    # If advance_time re-polled this, it would explode (not in orders_by_id).
    client.get_order_by_id_exc = RuntimeError("should not be called")
    assert broker.advance_time(NOW) == []


def test_cancel_order_calls_cancel_then_refetches(broker, client):
    order_id = uuid.uuid4()
    client.orders_by_id[str(order_id)] = fake_alpaca_order(id=order_id, status=AlpacaOrderStatus.CANCELED, qty="10")

    order = broker.cancel_order(str(order_id))

    assert client.cancel_calls == [str(order_id)]
    assert order.status == OrderStatus.CANCELED


def test_get_positions_coerces_string_numerics_to_float(broker, client):
    client.positions = [fake_position(symbol="AAPL", qty="10.5", avg_entry_price="150.25")]

    positions = broker.get_positions()

    assert positions["AAPL"].qty == 10.5
    assert positions["AAPL"].avg_entry_price == 150.25
    assert isinstance(positions["AAPL"].qty, float)


def test_get_account_coerces_string_numerics_and_extracts_account_id(broker, client):
    client.account = fake_account(cash="50000.00", equity="52000.00", buying_power="49000.00", account_number="ACC-123")

    account = broker.get_account()

    assert account.cash == 50000.0
    assert account.equity == 52000.0
    assert account.buying_power == 49000.0
    assert account.account_id == "ACC-123"
    assert isinstance(account.equity, float)


@pytest.mark.parametrize("alpaca_status,expected", [
    (AlpacaOrderStatus.FILLED, OrderStatus.FILLED),
    (AlpacaOrderStatus.PARTIALLY_FILLED, OrderStatus.PARTIALLY_FILLED),
    (AlpacaOrderStatus.REJECTED, OrderStatus.REJECTED),
    (AlpacaOrderStatus.CANCELED, OrderStatus.CANCELED),
    (AlpacaOrderStatus.EXPIRED, OrderStatus.CANCELED),
    (AlpacaOrderStatus.DONE_FOR_DAY, OrderStatus.CANCELED),
    (AlpacaOrderStatus.NEW, OrderStatus.NEW),
    (AlpacaOrderStatus.ACCEPTED, OrderStatus.NEW),
    (AlpacaOrderStatus.PENDING_NEW, OrderStatus.NEW),
    (AlpacaOrderStatus.HELD, OrderStatus.NEW),
    (AlpacaOrderStatus.CALCULATED, OrderStatus.NEW),
])
def test_status_mapping_never_misclassifies_open_orders_as_done(broker, client, alpaca_status, expected):
    """An unrecognized/in-flight status must default to NEW (open), never
    be mistaken for FILLED or CANCELED in either direction."""
    order_id = uuid.uuid4()
    client.orders_by_id[str(order_id)] = fake_alpaca_order(id=order_id, status=alpaca_status, qty="10")

    order = broker.get_order(str(order_id))

    assert order.status == expected


def test_list_orders_converts_results(broker, client):
    order_id = uuid.uuid4()
    client.list_orders_result = [
        fake_alpaca_order(id=order_id, status=AlpacaOrderStatus.FILLED, qty="5", filled_qty="5", filled_avg_price="100.0"),
    ]

    orders = broker.list_orders(since=NOW)

    assert len(orders) == 1
    assert orders[0].id == str(order_id)
    assert orders[0].status == OrderStatus.FILLED


def test_list_orders_registers_open_orders_for_future_advance_time_polling(broker, client):
    """Reconciliation uses list_orders() to recover orders the local DB
    never learned about (e.g. a crash between submit and persist). Those
    recovered orders must still be pollable to completion afterwards --
    prove list_orders() feeds the same internal tracking advance_time()
    reads, not just a one-off snapshot."""
    order_id = uuid.uuid4()
    client.list_orders_result = [fake_alpaca_order(id=order_id, status=AlpacaOrderStatus.NEW, qty="5", filled_qty="0")]
    broker.list_orders(since=NOW)

    client.orders_by_id[str(order_id)] = fake_alpaca_order(
        id=order_id, status=AlpacaOrderStatus.FILLED, qty="5", filled_qty="5", filled_avg_price="100.0",
    )
    updated = broker.advance_time(NOW)

    assert len(updated) == 1
    assert updated[0].status == OrderStatus.FILLED


def test_list_orders_passes_since_as_the_after_filter(broker, client):
    broker.list_orders(since=NOW)

    assert len(client.get_orders_calls) == 1
    assert client.get_orders_calls[0].after == NOW
