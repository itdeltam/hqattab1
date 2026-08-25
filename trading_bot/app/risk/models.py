"""Plain data structures the Risk Engine operates on. No pandas, no app.*
imports beyond this package -- kept dependency-free so app/risk can be
unit-tested in total isolation from the strategy, backtester, or broker.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Position:
    symbol: str
    shares: float
    avg_cost: float
    current_price: float

    @property
    def market_value(self) -> float:
        return self.shares * self.current_price

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.avg_cost == 0:
            return 0.0
        return (self.current_price - self.avg_cost) / self.avg_cost


@dataclass(frozen=True)
class PortfolioState:
    equity: float
    day_start_equity: float
    week_start_equity: float
    peak_equity: float
    positions: dict[str, Position] = field(default_factory=dict)
    # symbol -> symbol -> correlation, e.g. {"A": {"B": 0.8}, "B": {"A": 0.8}}.
    # None (or a missing pair) means "unknown" -- treated as uncorrelated,
    # never as a reason to block a trade.
    correlations: dict[str, dict[str, float]] | None = None


@dataclass(frozen=True)
class ProposedOrder:
    symbol: str
    side: str  # "buy" | "sell"
    shares: float
    price: float
    # Free-form context from the Strategy (e.g. confidence, signal score).
    # The Risk Engine must never let anything in here change a veto
    # decision -- it exists purely for logging/explainability.
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {self.side!r}")

    @property
    def notional(self) -> float:
        return abs(self.shares) * self.price

    def with_shares(self, shares: float) -> "ProposedOrder":
        return ProposedOrder(self.symbol, self.side, shares, self.price, self.metadata)


@dataclass(frozen=True)
class VetoedOrder:
    order: ProposedOrder
    reason: str


@dataclass(frozen=True)
class RiskDecision:
    approved_orders: list[ProposedOrder]
    vetoed_orders: list[VetoedOrder]
    kill_switch_engaged: bool
    notes: list[str] = field(default_factory=list)
