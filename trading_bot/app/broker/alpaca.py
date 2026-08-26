"""Real Alpaca adapter. Implements the exact same interface as
PaperBroker (app/broker/paper.py) -- submit_order, advance_time,
cancel_order, get_order, get_positions, get_account -- so the Trading
Engine, OrderManager, Portfolio, and reconciliation logic all work
unchanged whether they're wired to the local simulator or this class.
Per the confirmed architecture, PAPER and LIVE modes both run through
this same class; only `base_url` (and the API keys it's paired with)
differs, chosen by app/broker/factory.py from Settings.

Key design decision, worth calling out because it's easy to get backwards:
submit_order() only converts Alpaca's own APIError into a REJECTED Order
-- that is a definitive, authoritative "the broker refused this order."
Any other exception (a network timeout, a connection drop, a 5xx) is left
to propagate uncaught. We must never guess that an order was rejected
when we simply failed to find out what happened to it -- silently
recording "rejected" on an infrastructure fault could cause a real order
to go untracked, or, worse, invite a retry that double-submits. An
unknown outcome has to surface as a crash (for Stage 8's watchdog to
alert on and retry the whole cycle), never as a fabricated verdict.

Numeric fields on alpaca-py's response models (qty, cash, equity, ...)
are typed as `str | float | None` because Alpaca's raw JSON API returns
them as strings -- every one is explicitly float()'d when crossing into
our own domain models.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol

from alpaca.common.exceptions import APIError
from alpaca.trading.enums import OrderSide as AlpacaOrderSide
from alpaca.trading.enums import OrderStatus as AlpacaOrderStatus
from alpaca.trading.enums import QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest

from app.broker.models import (
    AccountSnapshot,
    BrokerPosition,
    Fill,
    Order,
    OrderRequest,
    OrderSide,
    OrderStatus,
)

# Alpaca has many more in-flight states than our own OrderStatus. Anything
# not explicitly recognized as filled/partially-filled/rejected/terminal
# defaults to NEW (still open) -- an unrecognized status must never be
# mistaken for "done," in either direction.
_TERMINAL_UNFILLED = {
    AlpacaOrderStatus.CANCELED,
    AlpacaOrderStatus.EXPIRED,
    AlpacaOrderStatus.DONE_FOR_DAY,
    AlpacaOrderStatus.STOPPED,
    AlpacaOrderStatus.SUSPENDED,
    AlpacaOrderStatus.REPLACED,
    AlpacaOrderStatus.PENDING_CANCEL,
    AlpacaOrderStatus.PENDING_REPLACE,
}


def _map_status(alpaca_status: AlpacaOrderStatus) -> OrderStatus:
    if alpaca_status == AlpacaOrderStatus.FILLED:
        return OrderStatus.FILLED
    if alpaca_status == AlpacaOrderStatus.PARTIALLY_FILLED:
        return OrderStatus.PARTIALLY_FILLED
    if alpaca_status == AlpacaOrderStatus.REJECTED:
        return OrderStatus.REJECTED
    if alpaca_status in _TERMINAL_UNFILLED:
        return OrderStatus.CANCELED
    return OrderStatus.NEW


def _rejection_message(exc: APIError) -> str:
    try:
        return exc.message
    except Exception:
        return str(exc)


class AlpacaTradingClient(Protocol):
    """The slice of alpaca-py's TradingClient this adapter depends on --
    narrow enough to fake completely in tests, with no real network."""

    def submit_order(self, order_data): ...
    def get_order_by_id(self, order_id): ...
    def cancel_order_by_id(self, order_id) -> None: ...
    def get_all_positions(self): ...
    def get_account(self): ...
    def get_orders(self, filter=None): ...


class AlpacaBroker:
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        base_url: str,
        paper: bool = True,
        trading_client: AlpacaTradingClient | None = None,
    ) -> None:
        self._orders: dict[str, Order] = {}
        if trading_client is not None:
            self._client = trading_client
        else:
            from alpaca.trading.client import TradingClient

            self._client = TradingClient(
                api_key=api_key, secret_key=secret_key, paper=paper, url_override=base_url,
            )

    def _convert_order(self, alpaca_order) -> Order:
        request = OrderRequest(
            symbol=alpaca_order.symbol,
            side=OrderSide(alpaca_order.side.value),
            qty=float(alpaca_order.qty),
        )
        status = _map_status(alpaca_order.status)

        filled_qty = float(alpaca_order.filled_qty) if alpaca_order.filled_qty else 0.0
        filled_avg_price = float(alpaca_order.filled_avg_price) if alpaca_order.filled_avg_price else None
        # Alpaca's order object exposes an aggregate filled_qty/filled_avg_price,
        # not itemized executions. A single synthetic Fill reproduces our
        # Order.filled_qty / avg_fill_price properties exactly; per-fill
        # granularity isn't needed anywhere downstream.
        fills = []
        if filled_qty > 0 and filled_avg_price is not None:
            fills = [Fill(
                qty=filled_qty, price=filled_avg_price,
                timestamp=alpaca_order.filled_at or alpaca_order.submitted_at,
            )]

        return Order(
            id=str(alpaca_order.id),
            request=request,
            status=status,
            submitted_at=alpaca_order.submitted_at,
            fills=fills,
        )

    def submit_order(self, request: OrderRequest, now: datetime) -> Order:
        order_data = MarketOrderRequest(
            symbol=request.symbol,
            qty=request.qty,
            side=AlpacaOrderSide.BUY if request.side == OrderSide.BUY else AlpacaOrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        try:
            alpaca_order = self._client.submit_order(order_data=order_data)
        except APIError as exc:
            # Alpaca itself refused the order (insufficient buying power,
            # unknown symbol, market closed, etc.) -- a definitive verdict,
            # safe to represent locally without ever having a broker order id.
            return Order(
                id=str(uuid.uuid4()), request=request, status=OrderStatus.REJECTED,
                submitted_at=now, rejection_reason=_rejection_message(exc),
            )

        order = self._convert_order(alpaca_order)
        self._orders[order.id] = order
        return order

    def get_order(self, order_id: str) -> Order:
        try:
            alpaca_order = self._client.get_order_by_id(order_id)
        except APIError as exc:
            # Translate to KeyError so reconciliation's "order unknown to
            # the broker" branch works identically to PaperBroker's.
            raise KeyError(order_id) from exc

        order = self._convert_order(alpaca_order)
        self._orders[order.id] = order
        return order

    def advance_time(self, now: datetime) -> list[Order]:
        """Unlike PaperBroker, fills happen on Alpaca's own servers --
        there's nothing to simulate. This just re-polls every locally
        known open order and returns the ones whose status or filled
        quantity actually changed. `now` is accepted only for interface
        parity with PaperBroker/OrderManager; it drives no behavior here.
        """
        updated = []
        for order_id, cached in list(self._orders.items()):
            if not cached.status.is_open:
                continue
            fresh = self.get_order(order_id)
            if fresh.status != cached.status or fresh.filled_qty != cached.filled_qty:
                updated.append(fresh)
        return updated

    def cancel_order(self, order_id: str) -> Order:
        self._client.cancel_order_by_id(order_id)
        return self.get_order(order_id)

    def list_orders(self, since: datetime) -> list[Order]:
        """Used by startup reconciliation to recover orders that reached
        Alpaca but were never persisted locally at all (e.g. the process
        crashed between submit_order() succeeding and the DB write that
        would have recorded it) -- resyncing only *known* local order ids
        can't find those, since it never had an id to look up."""
        alpaca_orders = self._client.get_orders(
            filter=GetOrdersRequest(status=QueryOrderStatus.ALL, after=since)
        )
        orders = [self._convert_order(o) for o in alpaca_orders]
        for order in orders:
            self._orders[order.id] = order
        return orders

    def get_positions(self) -> dict[str, BrokerPosition]:
        positions = self._client.get_all_positions()
        return {
            p.symbol: BrokerPosition(symbol=p.symbol, qty=float(p.qty), avg_entry_price=float(p.avg_entry_price))
            for p in positions
        }

    def get_account(self) -> AccountSnapshot:
        account = self._client.get_account()
        return AccountSnapshot(
            cash=float(account.cash),
            equity=float(account.equity),
            buying_power=float(account.buying_power),
            account_id=str(account.account_number) if account.account_number else None,
        )
