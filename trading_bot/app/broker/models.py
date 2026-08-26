"""Broker-facing data structures shared by the paper simulator (Stage 5)
and, later, the real Alpaca adapter (Stage 9) -- both live under
app/broker/ and are meant to expose the same shape so the future Trading
Engine (Stage 6) can be written against one interface."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELED = "canceled"

    @property
    def is_open(self) -> bool:
        return self in (OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED)


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: OrderSide
    qty: float


@dataclass(frozen=True)
class Fill:
    qty: float
    price: float
    timestamp: datetime


@dataclass
class Order:
    id: str
    request: OrderRequest
    status: OrderStatus
    submitted_at: datetime
    fills: list[Fill] = field(default_factory=list)
    rejection_reason: str | None = None
    next_fill_attempt_at: datetime | None = None

    @property
    def filled_qty(self) -> float:
        return sum(f.qty for f in self.fills)

    @property
    def remaining_qty(self) -> float:
        return self.request.qty - self.filled_qty

    @property
    def avg_fill_price(self) -> float | None:
        if not self.fills:
            return None
        return sum(f.qty * f.price for f in self.fills) / self.filled_qty


@dataclass(frozen=True)
class BrokerPosition:
    symbol: str
    qty: float
    avg_entry_price: float


@dataclass(frozen=True)
class AccountSnapshot:
    cash: float
    equity: float
    buying_power: float
    account_id: str | None = None
