"""Risk limit values. Deliberately a plain, dependency-free dataclass --
the Risk Engine must be unit-testable in total isolation, with no import
of app.config or anything else that pulls in the wider app. See
app/risk/config.py for how these get populated from Settings + YAML in
the real app.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    max_position_pct: float = 0.10
    max_daily_loss_pct: float = 0.02
    max_weekly_loss_pct: float = 0.05
    max_drawdown_pct: float = 0.15
    allow_leverage: bool = False
    max_leverage: float = 1.0

    # Correlation limit: no two positions with pairwise correlation at or
    # above max_correlation may together exceed max_correlated_group_pct
    # of equity. Pairwise only in v1 -- not full cluster/graph analysis.
    max_correlation: float = 0.70
    max_correlated_group_pct: float = 0.25

    # Anti-martingale: refuse to add to a position already underwater by
    # more than this fraction. Doesn't affect opening a brand-new position.
    max_add_to_loser_pct: float = 0.05
