"""Shared rebalancing math used by both the backtester (Stage 3) and the
live/paper Trading Engine (Stage 6), so a fix or change to this logic
never has to be made twice. Pure functions only -- no broker, no
database, no Risk Engine -- callers decide what to do with the result
(the backtester executes trades directly; the Trading Engine wraps them
as ProposedOrder objects for the Risk Engine to approve or veto first).
"""
from __future__ import annotations

import pandas as pd

from app.strategy.params import StrategyParams
from app.strategy.selection import select_with_buffer
from app.strategy.sizing import inverse_vol_weights

MIN_TRADE_VALUE = 1.00  # skip dust trades below this notional


def compute_target_weights(
    eligible: pd.Series,
    scores: pd.Series,
    vols: pd.Series,
    current_holdings: set[str],
    params: StrategyParams,
) -> tuple[dict[str, float], set[str]]:
    """Returns (target_weights, selected_momentum_holdings) as of one
    rebalance date. `eligible`/`scores`/`vols` are cross-sectional (one
    value per symbol), already computed through the prior session's close
    by the caller -- this function has no notion of "prior" vs "current"
    date, it just operates on whatever it's handed.
    """
    # trend_filter needs fewer days of history than momentum_score does
    # (the momentum skip adds a few extra days on top). In that narrow
    # window an asset can be trend-eligible with a still-NaN score;
    # pandas' sort_values() sorts NaN last but does not drop it, so an
    # asset with an undefined rank could otherwise still get selected.
    # Require both explicitly so "eligible" always means "rankable".
    rankable = eligible & scores.notna()
    selected = select_with_buffer(scores, rankable, current_holdings, params)
    # Only assets with a valid (non-NaN) vol estimate can be sized.
    selected = {s for s in selected if pd.notna(vols.get(s))}

    sleeve_frac = len(selected) / params.top_k if params.top_k else 0.0
    weights: dict[str, float] = {}
    if selected:
        inv_weights = inverse_vol_weights(vols[list(selected)])
        for symbol in selected:
            weights[symbol] = inv_weights[symbol] * sleeve_frac

    defensive = params.defensive_asset
    weights[defensive] = weights.get(defensive, 0.0) + (1.0 - sleeve_frac)

    return weights, selected


def compute_order_deltas(
    weights: dict[str, float],
    current_shares: dict[str, float],
    reference_prices: pd.Series,
    equity: float,
    min_trade_value: float = MIN_TRADE_VALUE,
) -> dict[str, float]:
    """Target-weight dollar sizing against `reference_prices` (the last
    known price -- prior close in the backtester, latest quote live),
    diffed against current holdings. Returns {symbol: delta_shares}
    (positive = buy, negative = sell) for symbols where the delta clears
    `min_trade_value`, skipping dust trades and symbols with no price.
    """
    deltas: dict[str, float] = {}
    for symbol in current_shares:
        reference_price = reference_prices.get(symbol)
        if reference_price is None or pd.isna(reference_price):
            continue

        target_weight = weights.get(symbol, 0.0)
        target_shares = (target_weight * equity) / reference_price
        delta = target_shares - current_shares[symbol]

        if delta == 0 or abs(delta) * reference_price < min_trade_value:
            continue

        deltas[symbol] = delta

    return deltas
