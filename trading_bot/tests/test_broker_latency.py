from datetime import datetime, timedelta

from app.backtesting.costs import FixedBpsSlippage
from app.broker.latency import FixedLatency, RandomLatency, ZeroLatency
from app.broker.paper import PaperBroker
from app.broker.models import OrderRequest, OrderSide, OrderStatus

NOW = datetime(2024, 1, 2, 9, 30)


def make_broker(prices, latency_model, seed=0):
    return PaperBroker(
        starting_cash=100_000.0,
        price_lookup=lambda s: prices.get(s),
        slippage_model=FixedBpsSlippage(bps=0),
        latency_model=latency_model,
        seed=seed,
    )


def test_zero_latency_fills_on_first_advance_time_call():
    broker = make_broker({"AAA": 100.0}, ZeroLatency())
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)

    broker.advance_time(NOW)

    assert broker.get_order(order.id).status == OrderStatus.FILLED


def test_fixed_latency_delays_fill_until_scheduled_time():
    broker = make_broker({"AAA": 100.0}, FixedLatency(seconds=60))
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)

    broker.advance_time(NOW)
    assert broker.get_order(order.id).status == OrderStatus.NEW

    broker.advance_time(NOW + timedelta(seconds=59))
    assert broker.get_order(order.id).status == OrderStatus.NEW

    broker.advance_time(NOW + timedelta(seconds=60))
    assert broker.get_order(order.id).status == OrderStatus.FILLED


def test_fixed_latency_fill_price_uses_price_at_fill_time_not_submit_time():
    prices = {"AAA": 100.0}
    broker = make_broker(prices, FixedLatency(seconds=60))
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)

    prices["AAA"] = 150.0  # price moves during the latency window
    broker.advance_time(NOW + timedelta(seconds=60))

    assert broker.get_order(order.id).avg_fill_price == 150.0


def test_random_latency_is_deterministic_given_a_seed():
    broker_a = make_broker({"AAA": 100.0}, RandomLatency(min_seconds=1, max_seconds=120), seed=42)
    order_a = broker_a.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)

    broker_b = make_broker({"AAA": 100.0}, RandomLatency(min_seconds=1, max_seconds=120), seed=42)
    order_b = broker_b.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)

    assert order_a.next_fill_attempt_at == order_b.next_fill_attempt_at


def test_random_latency_stays_within_configured_bounds():
    broker = make_broker({"AAA": 100.0}, RandomLatency(min_seconds=1, max_seconds=120))
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)

    delay = order.next_fill_attempt_at - NOW
    assert timedelta(seconds=1) <= delay <= timedelta(seconds=120)


def test_rejected_orders_have_no_latency_applied():
    broker = make_broker({"AAA": 100.0}, FixedLatency(seconds=60))
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, -1), now=NOW)

    assert order.status == OrderStatus.REJECTED
    assert order.next_fill_attempt_at is None
