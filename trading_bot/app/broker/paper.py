"""In-process paper-trading broker simulator. Fully offline and
deterministic (given a seed) -- no network, no real Alpaca connection.
This is NOT the Stage 9 Alpaca adapter; it exists so the future Trading
Engine (Stage 6) can be built and tested against a realistic broker
contract (fills, rejections, partial fills, latency) before any real
broker integration exists.

Time is never read from the wall clock -- every call takes an explicit
`now`, exactly like the backtester never reads real time. Fills are never
generated inside submit_order(); the caller must call advance_time(now)
to let pending orders resolve, which models a real broker's asynchronous
order-acknowledgement -> fill flow instead of a same-call, latency-free
fill that would remain untested until Stage 9.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime
from typing import Callable

from app.backtesting.costs import FixedBpsSlippage, SlippageModel
from app.broker.fills import FillQuantityModel, FullFillModel
from app.broker.latency import LatencyModel, ZeroLatency
from app.broker.models import (
    AccountSnapshot,
    BrokerPosition,
    Fill,
    Order,
    OrderRequest,
    OrderSide,
    OrderStatus,
)

PriceLookup = Callable[[str], "float | None"]
_EPSILON = 1e-9


class PaperBroker:
    def __init__(
        self,
        starting_cash: float,
        price_lookup: PriceLookup,
        slippage_model: SlippageModel | None = None,
        fill_quantity_model: FillQuantityModel | None = None,
        latency_model: LatencyModel | None = None,
        seed: int = 0,
    ):
        self.cash = starting_cash
        self._price_lookup = price_lookup
        self.slippage_model = slippage_model or FixedBpsSlippage(bps=5.0)
        self.fill_quantity_model = fill_quantity_model or FullFillModel()
        self.latency_model = latency_model or ZeroLatency()
        self._rng = random.Random(seed)
        self._positions: dict[str, BrokerPosition] = {}
        self._orders: dict[str, Order] = {}

    def submit_order(self, request: OrderRequest, now: datetime) -> Order:
        order_id = str(uuid.uuid4())
        reference_price = self._price_lookup(request.symbol)
        rejection_reason = self._validate(request, reference_price)

        if rejection_reason:
            order = Order(
                id=order_id, request=request, status=OrderStatus.REJECTED,
                submitted_at=now, rejection_reason=rejection_reason,
            )
        else:
            order = Order(
                id=order_id, request=request, status=OrderStatus.NEW,
                submitted_at=now, next_fill_attempt_at=now + self.latency_model.delay(self._rng),
            )

        self._orders[order_id] = order
        return order

    def _validate(self, request: OrderRequest, reference_price: float | None) -> str | None:
        if request.qty <= 0:
            return "invalid order quantity: must be positive"
        if reference_price is None:
            return f"no market data for {request.symbol}"

        if request.side == OrderSide.SELL:
            held_qty = self._positions[request.symbol].qty if request.symbol in self._positions else 0.0
            if request.qty > held_qty + _EPSILON:
                return f"insufficient shares to sell: hold {held_qty}, requested {request.qty}"

        if request.side == OrderSide.BUY:
            estimated_cost = request.qty * reference_price
            if estimated_cost > self.cash + _EPSILON:
                return f"insufficient buying power: need ~{estimated_cost:.2f}, have {self.cash:.2f}"

        return None

    def advance_time(self, now: datetime) -> list[Order]:
        """Resolves any pending fills whose scheduled time has arrived.
        The simulator never fills anything on its own -- this must be
        called periodically by the caller."""
        updated = []
        for order in self._orders.values():
            if not order.status.is_open:
                continue
            if order.next_fill_attempt_at is None or order.next_fill_attempt_at > now:
                continue
            self._attempt_fill(order, now)
            updated.append(order)
        return updated

    def _attempt_fill(self, order: Order, now: datetime) -> None:
        reference_price = self._price_lookup(order.request.symbol)
        if reference_price is None:
            # Market data disappeared after acceptance. Fail safe: retry
            # later rather than fill blind or crash.
            order.next_fill_attempt_at = now + self.latency_model.delay(self._rng)
            return

        fill_qty = min(
            self.fill_quantity_model.next_fill_qty(order.remaining_qty, self._rng),
            order.remaining_qty,
        )
        fill_price = self.slippage_model.fill_price(reference_price, order.request.side.value)

        order.fills.append(Fill(qty=fill_qty, price=fill_price, timestamp=now))
        self._apply_fill_to_account(order.request.symbol, order.request.side, fill_qty, fill_price)

        if order.remaining_qty <= _EPSILON:
            order.status = OrderStatus.FILLED
            order.next_fill_attempt_at = None
        else:
            order.status = OrderStatus.PARTIALLY_FILLED
            order.next_fill_attempt_at = now + self.latency_model.delay(self._rng)

    def _apply_fill_to_account(self, symbol: str, side: OrderSide, qty: float, price: float) -> None:
        sign = 1 if side == OrderSide.BUY else -1
        self.cash -= sign * qty * price

        existing = self._positions.get(symbol)
        if side == OrderSide.BUY:
            if existing:
                total_qty = existing.qty + qty
                new_avg = (existing.qty * existing.avg_entry_price + qty * price) / total_qty
                self._positions[symbol] = BrokerPosition(symbol, total_qty, new_avg)
            else:
                self._positions[symbol] = BrokerPosition(symbol, qty, price)
        else:
            remaining = existing.qty - qty
            if remaining <= _EPSILON:
                del self._positions[symbol]
            else:
                self._positions[symbol] = BrokerPosition(symbol, remaining, existing.avg_entry_price)

    def cancel_order(self, order_id: str) -> Order:
        order = self._orders[order_id]
        if order.status.is_open:
            order.status = OrderStatus.CANCELED
            order.next_fill_attempt_at = None
        return order

    def get_order(self, order_id: str) -> Order:
        return self._orders[order_id]

    def list_orders(self, since: datetime) -> list[Order]:
        return [order for order in self._orders.values() if order.submitted_at >= since]

    def get_positions(self) -> dict[str, BrokerPosition]:
        return dict(self._positions)

    def get_account(self) -> AccountSnapshot:
        market_value = sum(
            position.qty * (self._price_lookup(position.symbol) or position.avg_entry_price)
            for position in self._positions.values()
        )
        equity = self.cash + market_value
        return AccountSnapshot(cash=self.cash, equity=equity, buying_power=self.cash)
