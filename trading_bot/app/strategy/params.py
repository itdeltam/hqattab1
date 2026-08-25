"""Fixed parameter set from the Stage 2 research spec
(research/stage2_strategy_math_spec.ipynb). Backtested as a fixed set, not
curve-fit -- see that notebook's section 8 for the justification."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyParams:
    sma_window: int = 200
    trend_mom_window: int = 252
    momentum_lookbacks: tuple[int, ...] = (63, 126, 252)
    momentum_skip: int = 5
    vol_window: int = 63
    top_k: int = 6
    rank_buffer: int = 4
    defensive_asset: str = "SHY"
