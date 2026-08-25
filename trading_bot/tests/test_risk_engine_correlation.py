from app.risk.engine import RiskEngine
from app.risk.limits import RiskLimits
from app.risk.models import PortfolioState, Position, ProposedOrder


def test_correlated_pair_exceeding_combined_cap_is_vetoed():
    # AAA already 20% of equity; adding BBB (correlated 0.9 >= 0.7 threshold)
    # at another 20% would put the pair at 40%, over the 25% cap.
    positions = {"AAA": Position(symbol="AAA", shares=200, avg_cost=100.0, current_price=100.0)}
    correlations = {"AAA": {"BBB": 0.9}, "BBB": {"AAA": 0.9}}
    portfolio = PortfolioState(
        equity=100_000, day_start_equity=100_000, week_start_equity=100_000,
        peak_equity=100_000, positions=positions, correlations=correlations,
    )
    engine = RiskEngine(RiskLimits(max_position_pct=1.0, max_correlation=0.7, max_correlated_group_pct=0.25))
    order = ProposedOrder(symbol="BBB", side="buy", shares=200, price=100.0)

    decision = engine.evaluate([order], portfolio)

    assert decision.approved_orders == []
    assert "correlated" in decision.vetoed_orders[0].reason.lower()


def test_uncorrelated_pair_is_not_blocked_by_correlation_limit():
    positions = {"AAA": Position(symbol="AAA", shares=200, avg_cost=100.0, current_price=100.0)}
    correlations = {"AAA": {"BBB": 0.1}, "BBB": {"AAA": 0.1}}
    portfolio = PortfolioState(
        equity=100_000, day_start_equity=100_000, week_start_equity=100_000,
        peak_equity=100_000, positions=positions, correlations=correlations,
    )
    engine = RiskEngine(RiskLimits(max_position_pct=1.0, max_correlation=0.7, max_correlated_group_pct=0.25))
    order = ProposedOrder(symbol="BBB", side="buy", shares=200, price=100.0)

    decision = engine.evaluate([order], portfolio)

    assert len(decision.approved_orders) == 1


def test_correlated_pair_within_combined_cap_is_approved():
    positions = {"AAA": Position(symbol="AAA", shares=50, avg_cost=100.0, current_price=100.0)}  # 5%
    correlations = {"AAA": {"BBB": 0.9}, "BBB": {"AAA": 0.9}}
    portfolio = PortfolioState(
        equity=100_000, day_start_equity=100_000, week_start_equity=100_000,
        peak_equity=100_000, positions=positions, correlations=correlations,
    )
    engine = RiskEngine(RiskLimits(max_position_pct=1.0, max_correlation=0.7, max_correlated_group_pct=0.25))
    order = ProposedOrder(symbol="BBB", side="buy", shares=50, price=100.0)  # another 5%, combined 10% < 25%

    decision = engine.evaluate([order], portfolio)

    assert len(decision.approved_orders) == 1


def test_missing_correlation_data_never_blocks_a_trade():
    positions = {"AAA": Position(symbol="AAA", shares=200, avg_cost=100.0, current_price=100.0)}
    portfolio = PortfolioState(
        equity=100_000, day_start_equity=100_000, week_start_equity=100_000,
        peak_equity=100_000, positions=positions, correlations=None,
    )
    engine = RiskEngine(RiskLimits(max_position_pct=1.0))
    order = ProposedOrder(symbol="BBB", side="buy", shares=200, price=100.0)

    decision = engine.evaluate([order], portfolio)

    assert len(decision.approved_orders) == 1
