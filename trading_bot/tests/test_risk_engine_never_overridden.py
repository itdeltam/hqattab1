"""The flagship test for Stage 4: 'the Risk Engine must be a separate
module that can veto any trade the Strategy proposes -- no exceptions, no
overrides from the strategy is confident' is a project-level non-negotiable
rule, not just a design intention. This proves it mechanically: an order
carrying a maximal-confidence justification from the Strategy is vetoed
exactly the same as one with no metadata at all, under every limit this
engine enforces.
"""
import pytest

from app.risk.engine import RiskEngine
from app.risk.limits import RiskLimits
from app.risk.models import PortfolioState, Position, ProposedOrder

CONFIDENT_METADATA = {
    "confidence": "very high",
    "signal_score": 999.0,
    "strategy_note": "This is the highest-conviction signal the strategy has ever produced.",
    "override_requested": True,  # even an explicit override flag must be inert
}


def _confident_order(**kwargs) -> ProposedOrder:
    return ProposedOrder(metadata=dict(CONFIDENT_METADATA), **kwargs)


@pytest.mark.parametrize(
    "scenario_name,portfolio_kwargs,limits_kwargs,order_kwargs",
    [
        (
            "position_limit",
            dict(equity=100_000, positions={"AAA": Position("AAA", 100, 100.0, 100.0)}),
            dict(max_position_pct=0.10),
            dict(symbol="AAA", side="buy", shares=10, price=100.0),
        ),
        (
            "no_leverage",
            dict(equity=100_000, positions={"AAA": Position("AAA", 1000, 100.0, 100.0)}),  # already 100% invested
            dict(max_position_pct=1.0, allow_leverage=False),
            dict(symbol="BBB", side="buy", shares=10, price=100.0),  # a different symbol -- no headroom to buy it
        ),
        (
            "daily_loss_limit",
            dict(equity=97_000, day_start_equity=100_000),
            dict(max_daily_loss_pct=0.02),
            dict(symbol="AAA", side="buy", shares=10, price=100.0),
        ),
        (
            "weekly_loss_limit",
            dict(equity=94_000, day_start_equity=95_000, week_start_equity=100_000),
            dict(max_daily_loss_pct=0.5, max_weekly_loss_pct=0.05),
            dict(symbol="AAA", side="buy", shares=10, price=100.0),
        ),
        (
            "drawdown_kill_switch",
            dict(equity=80_000, day_start_equity=80_000, week_start_equity=80_000, peak_equity=100_000),
            dict(max_drawdown_pct=0.15),
            dict(symbol="AAA", side="buy", shares=10, price=100.0),
        ),
        (
            "no_short_selling",
            dict(equity=100_000, positions={"AAA": Position("AAA", 10, 90.0, 100.0)}),
            dict(),
            dict(symbol="AAA", side="sell", shares=100, price=100.0),
        ),
        (
            "anti_martingale",
            dict(equity=100_000, positions={"AAA": Position("AAA", 100, 100.0, 90.0)}),
            dict(max_add_to_loser_pct=0.05),
            dict(symbol="AAA", side="buy", shares=10, price=90.0),
        ),
        (
            "correlation_limit",
            dict(
                equity=100_000,
                positions={"AAA": Position("AAA", 200, 100.0, 100.0)},
                correlations={"AAA": {"BBB": 0.9}, "BBB": {"AAA": 0.9}},
            ),
            dict(max_position_pct=1.0, max_correlation=0.7, max_correlated_group_pct=0.25),
            dict(symbol="BBB", side="buy", shares=200, price=100.0),
        ),
    ],
)
def test_high_confidence_metadata_never_overrides_a_veto(
    scenario_name, portfolio_kwargs, limits_kwargs, order_kwargs
):
    equity = portfolio_kwargs.get("equity", 100_000)
    defaults = dict(day_start_equity=equity, week_start_equity=equity, peak_equity=equity, positions={})
    defaults.update(portfolio_kwargs)
    portfolio = PortfolioState(**defaults)

    engine = RiskEngine(RiskLimits(**limits_kwargs))

    plain_order = ProposedOrder(**order_kwargs)
    confident_order = _confident_order(**order_kwargs)

    plain_decision = engine.evaluate([plain_order], portfolio)
    confident_decision = engine.evaluate([confident_order], portfolio)

    assert plain_decision.approved_orders == [], f"{scenario_name}: sanity check failed (plain order not vetoed)"
    assert confident_decision.approved_orders == [], (
        f"{scenario_name}: a 'very high confidence' order was approved despite the veto condition -- "
        "the Risk Engine must never be overridden by strategy confidence."
    )
    assert len(confident_decision.vetoed_orders) == len(plain_decision.vetoed_orders)
