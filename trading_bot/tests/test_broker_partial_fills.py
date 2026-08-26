from datetime import datetime

import pytest

from app.backtesting.costs import FixedBpsSlippage
from app.broker.fills import PartialFillModel
from app.broker.paper import PaperBroker
from app.broker.models import OrderRequest, OrderSide, OrderStatus

NOW = datetime(2024, 1, 2, 9, 30)


def make_broker(prices):
    return PaperBroker(
        starting_cash=1_000_000.0,
        price_lookup=lambda s: prices.get(s),
        slippage_model=FixedBpsSlippage(bps=0),
        fill_quantity_model=PartialFillModel(fraction=0.5, min_remaining_qty=10),
    )


def test_partial_fill_progresses_over_multiple_advance_time_calls():
    prices = {"AAA": 100.0}
    broker = make_broker(prices)
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 100), now=NOW)

    broker.advance_time(NOW)
    assert broker.get_order(order.id).status == OrderStatus.PARTIALLY_FILLED
    assert broker.get_order(order.id).filled_qty == pytest.approx(50)

    broker.advance_time(NOW)
    assert broker.get_order(order.id).filled_qty == pytest.approx(75)

    broker.advance_time(NOW)
    assert broker.get_order(order.id).filled_qty == pytest.approx(87.5)

    broker.advance_time(NOW)  # remaining (12.5) drops below min_remaining_qty -> finishes
    final = broker.get_order(order.id)
    assert final.status == OrderStatus.FILLED
    assert final.filled_qty == pytest.approx(100)


def test_partial_fill_never_exceeds_original_order_quantity():
    prices = {"AAA": 100.0}
    broker = make_broker(prices)
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 100), now=NOW)

    for _ in range(10):
        broker.advance_time(NOW)

    final = broker.get_order(order.id)
    assert final.filled_qty == pytest.approx(100)
    assert final.status == OrderStatus.FILLED


def test_avg_fill_price_is_correctly_weighted_across_partial_fills_at_different_prices():
    prices = {"AAA": 100.0}
    broker = make_broker(prices)
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 100), now=NOW)

    broker.advance_time(NOW)  # fills 50 @ 100
    prices["AAA"] = 110.0
    broker.advance_time(NOW)  # fills 25 @ 110
    prices["AAA"] = 120.0
    broker.advance_time(NOW)  # fills 12.5 @ 120
    broker.advance_time(NOW)  # fills remaining 12.5 @ 120

    final = broker.get_order(order.id)
    expected_avg = (50 * 100 + 25 * 110 + 12.5 * 120 + 12.5 * 120) / 100
    assert final.avg_fill_price == pytest.approx(expected_avg)


def test_position_reflects_cumulative_partial_fills_before_order_fully_completes():
    prices = {"AAA": 100.0}
    broker = make_broker(prices)
    broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 100), now=NOW)

    broker.advance_time(NOW)

    position = broker.get_positions()["AAA"]
    assert position.qty == pytest.approx(50)
