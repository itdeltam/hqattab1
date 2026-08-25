from datetime import datetime

import pytest

from app.backtesting.costs import FixedBpsSlippage
from app.broker.paper import PaperBroker
from app.broker.models import OrderRequest, OrderSide, OrderStatus

NOW = datetime(2024, 1, 2, 9, 30)


def make_broker(prices, **kwargs):
    return PaperBroker(starting_cash=100_000.0, price_lookup=lambda s: prices.get(s), **kwargs)


def test_market_buy_fills_completely_with_zero_latency():
    prices = {"AAA": 100.0}
    broker = make_broker(prices, slippage_model=FixedBpsSlippage(bps=0))

    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    broker.advance_time(NOW)

    filled = broker.get_order(order.id)
    assert filled.status == OrderStatus.FILLED
    assert filled.filled_qty == pytest.approx(10)
    assert filled.avg_fill_price == pytest.approx(100.0)


def test_buy_fill_price_includes_slippage_against_the_trader():
    prices = {"AAA": 100.0}
    broker = make_broker(prices, slippage_model=FixedBpsSlippage(bps=10))

    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    broker.advance_time(NOW)

    filled = broker.get_order(order.id)
    assert filled.avg_fill_price == pytest.approx(100.1)  # 10bps above reference


def test_sell_fill_price_includes_slippage_against_the_trader():
    prices = {"AAA": 100.0}
    broker = make_broker(prices, slippage_model=FixedBpsSlippage(bps=10))
    broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    broker.advance_time(NOW)

    order = broker.submit_order(OrderRequest("AAA", OrderSide.SELL, 10), now=NOW)
    broker.advance_time(NOW)

    filled = broker.get_order(order.id)
    assert filled.avg_fill_price == pytest.approx(99.9)  # 10bps below reference


def test_filled_buy_updates_cash_and_position():
    prices = {"AAA": 100.0}
    broker = make_broker(prices, slippage_model=FixedBpsSlippage(bps=0))

    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    broker.advance_time(NOW)

    assert broker.cash == pytest.approx(100_000.0 - 1_000.0)
    position = broker.get_positions()["AAA"]
    assert position.qty == pytest.approx(10)
    assert position.avg_entry_price == pytest.approx(100.0)


def test_filled_sell_updates_cash_and_removes_position_when_fully_closed():
    prices = {"AAA": 100.0}
    broker = make_broker(prices, slippage_model=FixedBpsSlippage(bps=0))
    broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    broker.advance_time(NOW)
    cash_after_buy = broker.cash

    broker.submit_order(OrderRequest("AAA", OrderSide.SELL, 10), now=NOW)
    broker.advance_time(NOW)

    assert broker.cash == pytest.approx(cash_after_buy + 1_000.0)
    assert "AAA" not in broker.get_positions()


def test_buying_more_of_existing_position_updates_weighted_avg_cost():
    prices = {"AAA": 100.0}
    broker = make_broker(prices, slippage_model=FixedBpsSlippage(bps=0))
    broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    broker.advance_time(NOW)

    prices["AAA"] = 200.0
    broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 10), now=NOW)
    broker.advance_time(NOW)

    position = broker.get_positions()["AAA"]
    assert position.qty == pytest.approx(20)
    assert position.avg_entry_price == pytest.approx(150.0)  # (10*100 + 10*200) / 20
