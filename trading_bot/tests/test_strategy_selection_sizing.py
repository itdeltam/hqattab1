import pandas as pd
import pytest

from app.strategy.params import StrategyParams
from app.strategy.selection import select_with_buffer
from app.strategy.sizing import inverse_vol_weights


def test_select_drops_ineligible_holding():
    params = StrategyParams(top_k=2, rank_buffer=1)
    scores = pd.Series({"A": 3.0, "B": 2.0, "C": 1.0, "D": 0.5})
    eligible = pd.Series({"A": True, "B": True, "C": True, "D": False})

    selected = select_with_buffer(scores, eligible, current_holdings={"D"}, params=params)

    assert "D" not in selected


def test_select_top_k_when_no_current_holdings():
    params = StrategyParams(top_k=2, rank_buffer=1)
    scores = pd.Series({"A": 3.0, "B": 2.0, "C": 1.0})
    eligible = pd.Series({"A": True, "B": True, "C": True})

    selected = select_with_buffer(scores, eligible, current_holdings=set(), params=params)

    assert selected == {"A", "B"}


def test_buffer_retains_marginally_ranked_holding():
    # A held at rank 3; top_k=2 means it's outside top-k but the buffer=1
    # (top_k + buffer = 3) should still retain it.
    params = StrategyParams(top_k=2, rank_buffer=1)
    scores = pd.Series({"A": 3.0, "B": 2.0, "C": 1.0})
    eligible = pd.Series({"A": True, "B": True, "C": True})

    kept = select_with_buffer(scores, eligible, current_holdings={"C"}, params=params)
    assert "C" in kept


def test_buffer_zero_drops_marginally_ranked_holding():
    params = StrategyParams(top_k=2, rank_buffer=0)
    scores = pd.Series({"A": 3.0, "B": 2.0, "C": 1.0})
    eligible = pd.Series({"A": True, "B": True, "C": True})

    kept = select_with_buffer(scores, eligible, current_holdings={"C"}, params=params)
    assert "C" not in kept


def test_inverse_vol_weights_sum_to_one():
    vols = pd.Series({"A": 0.10, "B": 0.20, "C": 0.30})
    weights = inverse_vol_weights(vols)
    assert abs(weights.sum() - 1.0) < 1e-12


def test_inverse_vol_weights_favor_lower_vol():
    vols = pd.Series({"LOW_VOL": 0.10, "HIGH_VOL": 0.40})
    weights = inverse_vol_weights(vols)
    assert weights["LOW_VOL"] > weights["HIGH_VOL"]
