"""A tiny mutable cell bridging market-data fetches to
TradingEngine.price_lookup.

TradingEngine is constructed once and lives for the whole process, but
its price_lookup callable is captured at construction time -- it can't be
swapped out per rebalance cycle. The scheduler instead calls update()
with a fresh quote snapshot immediately before each cycle; get() is what
the price_lookup callable handed to TradingEngine actually reads.

This matters for correctness, not just display: Position.unrealized_pnl_pct
(current_price vs avg_cost) drives the Risk Engine's anti-martingale rule
(app/risk/engine.py) -- by design, that value is only ever as fresh as the
last update() call, which happens immediately before the cycle that
depends on it.
"""
from __future__ import annotations


class LivePriceCache:
    def __init__(self) -> None:
        self._prices: dict[str, float] = {}

    def update(self, prices: dict[str, float]) -> None:
        self._prices = dict(prices)

    def get(self, symbol: str) -> float | None:
        return self._prices.get(symbol)
