"""Cross-sectional selection with a turnover-reducing rank buffer. Ported
from research/stage2_strategy_math_spec.ipynb section 4."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.strategy.params import StrategyParams


def select_with_buffer(
    scores: pd.Series,
    eligible: pd.Series,
    current_holdings: set[str],
    params: StrategyParams,
) -> set[str]:
    """One rebalance step. `scores`/`eligible` are cross-sectional (one
    value per asset) as of the rebalance date."""
    ranked = scores[eligible].sort_values(ascending=False)
    rank_of = {ticker: i + 1 for i, ticker in enumerate(ranked.index)}

    kept = {
        t for t in current_holdings
        if rank_of.get(t, np.inf) <= params.top_k + params.rank_buffer
    }

    new_selections = set(kept)
    for ticker in ranked.index:
        if len(new_selections) >= params.top_k:
            break
        new_selections.add(ticker)

    return new_selections
