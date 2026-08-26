"""How much of an order's remaining quantity fills on a given attempt.
Kept separate from PaperBroker so a test can plug in a deterministic
partial-fill schedule instead of relying on randomness."""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol


class FillQuantityModel(Protocol):
    def next_fill_qty(self, remaining_qty: float, rng: random.Random) -> float: ...


@dataclass(frozen=True)
class FullFillModel:
    """Every order fills completely on its first attempt. The default --
    matches a liquid-ETF assumption consistent with the rest of the
    project (see the Stage 2 universe choice)."""

    def next_fill_qty(self, remaining_qty: float, rng: random.Random) -> float:
        return remaining_qty


@dataclass(frozen=True)
class PartialFillModel:
    """Fills `fraction` of whatever remains on each attempt. Finishes off
    the remainder in one go once it drops below `min_remaining_qty`,
    rather than leaving an ever-shrinking dust quantity that never
    technically reaches zero."""

    fraction: float
    min_remaining_qty: float = 1e-6

    def next_fill_qty(self, remaining_qty: float, rng: random.Random) -> float:
        qty = remaining_qty * self.fraction
        if remaining_qty - qty < self.min_remaining_qty:
            return remaining_qty
        return qty


@dataclass(frozen=True)
class RandomPartialFillModel:
    """Fills a random fraction of the remainder in [min_fraction,
    max_fraction] each attempt, using the broker's seeded rng -- so tests
    stay deterministic despite the randomness."""

    min_fraction: float = 0.2
    max_fraction: float = 0.8
    min_remaining_qty: float = 1e-6

    def next_fill_qty(self, remaining_qty: float, rng: random.Random) -> float:
        qty = remaining_qty * rng.uniform(self.min_fraction, self.max_fraction)
        if remaining_qty - qty < self.min_remaining_qty:
            return remaining_qty
        return qty
