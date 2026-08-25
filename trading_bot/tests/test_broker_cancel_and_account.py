from datetime import datetime, timedelta

import pytest

from app.backtesting.costs import FixedBpsSlippage
from app.broker.fills import PartialFillModel
from app.broker.latency import FixedLatency
from app.broker.paper import PaperBroker
from app.broker.models import OrderRequest, OrderSide, OrderStatus

NOW = datetime(2024, 1, 2, 9, 30)


def make_broker(prices, **kwargs):
    kwargs.setdefault("slippage_model", FixedBpsSlippage(bps=0))
    return PaperBroker(starting_cash=100_000.0, price_lookup=lambda s: prices.get(s), **kwargs)


def test_canceling_a_pending_order_prevents_it_from_ever_filling():
    broker = make_broker({"AAA": 100.0}, latency_model=FixedLatency(seconds=60))
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)

    broker.cancel_order(order.id)
    broker.advance_time(NOW + timedelta(seconds=60))

    final = broker.get_order(order.id)
    assert final.status == OrderStatus.CANCELED
    assert final.fills == []


def test_canceling_a_partially_filled_order_stops_further_fills():
    broker = make_broker(
        {"AAA": 100.0}, fill_quantity_model=PartialFillModel(fraction=0.5, min_remaining_qty=10),
    )
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 100), now=NOW)
    broker.advance_time(NOW)  # partial fill: 50

    broker.cancel_order(order.id)
    broker.advance_time(NOW)

    final = broker.get_order(order.id)
    assert final.status == OrderStatus.CANCELED
    assert final.filled_qty == pytest.approx(50)


def test_canceling_an_already_filled_order_is_a_harmless_no_op():
    broker = make_broker({"AAA": 100.0})
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    broker.advance_time(NOW)

    result = broker.cancel_order(order.id)

    assert result.status == OrderStatus.FILLED  # unchanged, not overwritten to CANCELED


def test_account_equity_marks_positions_to_current_price():
    prices = {"AAA": 100.0}
    broker = make_broker(prices)
    broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    broker.advance_time(NOW)

    account_before = broker.get_account()
    assert account_before.equity == pytest.approx(100_000.0)  # cash out, position in, at same price

    prices["AAA"] = 150.0
    account_after = broker.get_account()
    assert account_after.equity == pytest.approx(100_000.0 - 1_000.0 + 1_500.0)


def test_account_buying_power_reflects_available_cash():
    broker = make_broker({"AAA": 100.0})
    broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 100), now=NOW)  # $10,000
    broker.advance_time(NOW)

    account = broker.get_account()
    assert account.buying_power == pytest.approx(90_000.0)
    assert account.cash == pytest.approx(90_000.0)
