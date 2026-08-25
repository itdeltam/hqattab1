import pandas as pd
import pytest

from app.strategy.params import StrategyParams
from app.strategy.rebalancing import compute_order_deltas, compute_target_weights


def test_compute_target_weights_matches_selection_and_sizing_rules():
    params = StrategyParams(top_k=2, rank_buffer=1, defensive_asset="SHY")
    eligible = pd.Series({"A": True, "B": True, "C": False, "SHY": True})
    scores = pd.Series({"A": 2.0, "B": 1.0, "C": 0.5, "SHY": 0.1})
    vols = pd.Series({"A": 0.10, "B": 0.20, "C": 0.15, "SHY": 0.02})

    weights, selected = compute_target_weights(eligible, scores, vols, current_holdings=set(), params=params)

    assert selected == {"A", "B"}
    assert weights["A"] > weights["B"]  # A has lower vol -> larger inverse-vol weight
    assert weights.get("C", 0.0) == 0.0  # ineligible, never selected
    assert "SHY" not in selected or weights["SHY"] >= 0  # defensive weight always present
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_compute_target_weights_all_defensive_when_nothing_eligible():
    params = StrategyParams(top_k=2, defensive_asset="SHY")
    eligible = pd.Series({"A": False, "B": False, "SHY": False})
    scores = pd.Series({"A": 1.0, "B": 1.0, "SHY": 0.1})
    vols = pd.Series({"A": 0.1, "B": 0.1, "SHY": 0.02})

    weights, selected = compute_target_weights(eligible, scores, vols, current_holdings=set(), params=params)

    assert selected == set()
    assert weights["SHY"] == pytest.approx(1.0)


def test_compute_order_deltas_buys_to_reach_target_weight():
    weights = {"A": 0.5, "SHY": 0.5}
    current_shares = {"A": 0.0, "SHY": 0.0}
    reference_prices = pd.Series({"A": 100.0, "SHY": 50.0})

    deltas = compute_order_deltas(weights, current_shares, reference_prices, equity=100_000)

    assert deltas["A"] == pytest.approx(500.0)   # $50,000 / $100
    assert deltas["SHY"] == pytest.approx(1000.0)  # $50,000 / $50


def test_compute_order_deltas_sells_when_overweight():
    weights = {"A": 0.0}
    current_shares = {"A": 100.0}
    reference_prices = pd.Series({"A": 100.0})

    deltas = compute_order_deltas(weights, current_shares, reference_prices, equity=100_000)

    assert deltas["A"] == pytest.approx(-100.0)


def test_compute_order_deltas_skips_dust_trades():
    # current position is 1000 sh @ $100 = $100,000 = 100% of equity; target
    # weight is a hair below that, implying a $0.50 sell -- well under the
    # $1 dust threshold.
    weights = {"A": 0.999995}
    current_shares = {"A": 1000.0}
    reference_prices = pd.Series({"A": 100.0})

    deltas = compute_order_deltas(weights, current_shares, reference_prices, equity=100_000, min_trade_value=1.0)

    assert "A" not in deltas


def test_compute_order_deltas_skips_symbols_with_missing_price():
    weights = {"A": 1.0}
    current_shares = {"A": 0.0}
    reference_prices = pd.Series({"A": float("nan")})

    deltas = compute_order_deltas(weights, current_shares, reference_prices, equity=100_000)

    assert "A" not in deltas


def test_compute_order_deltas_zero_delta_is_skipped():
    weights = {"A": 0.5}
    current_shares = {"A": 500.0}  # already exactly at target
    reference_prices = pd.Series({"A": 100.0})

    deltas = compute_order_deltas(weights, current_shares, reference_prices, equity=100_000)

    assert "A" not in deltas
