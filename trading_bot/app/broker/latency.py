"""How long an order sits before a fill attempt is made. The paper broker
never fills anything on submission -- see PaperBroker.advance_time -- so
these models control how long the caller's next advance_time(now) call
has to wait before that fill actually happens."""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol


class LatencyModel(Protocol):
    def delay(self, rng: random.Random) -> timedelta: ...


@dataclass(frozen=True)
class ZeroLatency:
    def delay(self, rng: random.Random) -> timedelta:
        return timedelta(0)


@dataclass(frozen=True)
class FixedLatency:
    seconds: float

    def delay(self, rng: random.Random) -> timedelta:
        return timedelta(seconds=self.seconds)


@dataclass(frozen=True)
class RandomLatency:
    min_seconds: float
    max_seconds: float

    def delay(self, rng: random.Random) -> timedelta:
        return timedelta(seconds=rng.uniform(self.min_seconds, self.max_seconds))
