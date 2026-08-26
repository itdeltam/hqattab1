from datetime import datetime

from app.broker.paper import PaperBroker
from app.broker.models import OrderRequest, OrderSide, OrderStatus

NOW = datetime(2024, 1, 2, 9, 30)


def make_broker(prices, starting_cash=100_000.0):
    return PaperBroker(starting_cash=starting_cash, price_lookup=lambda s: prices.get(s))


def test_zero_quantity_is_rejected():
    broker = make_broker({"AAA": 100.0})
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 0), now=NOW)

    assert order.status == OrderStatus.REJECTED
    assert "quantity" in order.rejection_reason


def test_negative_quantity_is_rejected():
    broker = make_broker({"AAA": 100.0})
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, -5), now=NOW)

    assert order.status == OrderStatus.REJECTED


def test_unknown_symbol_is_rejected():
    broker = make_broker({"AAA": 100.0})
    order = broker.submit_order(OrderRequest("ZZZZ", OrderSide.BUY, 10), now=NOW)

    assert order.status == OrderStatus.REJECTED
    assert "market data" in order.rejection_reason


def test_insufficient_buying_power_is_rejected():
    broker = make_broker({"AAA": 100.0}, starting_cash=500.0)
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)  # needs $1,000

    assert order.status == OrderStatus.REJECTED
    assert "buying power" in order.rejection_reason


def test_selling_more_than_held_is_rejected_never_shorts():
    broker = make_broker({"AAA": 100.0})
    broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 5), now=NOW)
    broker.advance_time(NOW)

    order = broker.submit_order(OrderRequest("AAA", OrderSide.SELL, 10), now=NOW)

    assert order.status == OrderStatus.REJECTED
    assert "insufficient shares" in order.rejection_reason


def test_selling_a_symbol_never_held_is_rejected():
    broker = make_broker({"AAA": 100.0})
    order = broker.submit_order(OrderRequest("AAA", OrderSide.SELL, 1), now=NOW)

    assert order.status == OrderStatus.REJECTED


def test_rejected_order_is_never_touched_by_advance_time():
    broker = make_broker({"AAA": 100.0}, starting_cash=500.0)
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)

    broker.advance_time(NOW)

    assert broker.get_order(order.id).status == OrderStatus.REJECTED
    assert broker.get_order(order.id).fills == []
