"""Commission and slippage models. Kept as small, swappable strategy
objects so a backtest can be run cost-free (to isolate signal quality) or
with realistic costs layered on top, without changing the engine."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class CommissionModel(Protocol):
    def commission(self, shares: float, price: float) -> float: ...


class SlippageModel(Protocol):
    def fill_price(self, reference_price: float, side: str) -> float: ...


@dataclass(frozen=True)
class ZeroCommission:
    """Matches Alpaca's actual commission structure for US equities/ETFs."""

    def commission(self, shares: float, price: float) -> float:
        return 0.0


@dataclass(frozen=True)
class PerShareCommission:
    rate_per_share: float
    minimum: float = 0.0

    def commission(self, shares: float, price: float) -> float:
        return max(self.minimum, abs(shares) * self.rate_per_share)


@dataclass(frozen=True)
class FixedBpsSlippage:
    """Models the bid/ask spread and market impact as a fixed number of
    basis points against the trader: buys fill above the reference price,
    sells fill below it."""

    bps: float

    def fill_price(self, reference_price: float, side: str) -> float:
        adj = self.bps / 10_000
        if side == "buy":
            return reference_price * (1 + adj)
        if side == "sell":
            return reference_price * (1 - adj)
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
