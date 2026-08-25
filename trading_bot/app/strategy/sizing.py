"""Position sizing. Ported from research/stage2_strategy_math_spec.ipynb
section 5."""
from __future__ import annotations

import pandas as pd


def inverse_vol_weights(vols: pd.Series) -> pd.Series:
    """Long-only, no-leverage weights inversely proportional to trailing
    vol, normalized to sum to 1. Lower-vol names get more weight, spreading
    risk contribution more evenly than equal-weighting would."""
    inv = 1.0 / vols
    return inv / inv.sum()
