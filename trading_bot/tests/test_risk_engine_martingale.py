from app.risk.engine import RiskEngine
from app.risk.limits import RiskLimits
from app.risk.models import PortfolioState, Position, ProposedOrder


def make_portfolio(positions, equity=100_000.0):
    return PortfolioState(
        equity=equity, day_start_equity=equity, week_start_equity=equity,
        peak_equity=equity, positions=positions,
    )


def test_refuses_to_add_to_a_losing_position_past_threshold():
    # Down 10%, threshold is 5% -- this is exactly "doubling down" on a loser.
    positions = {"AAA": Position(symbol="AAA", shares=100, avg_cost=100.0, current_price=90.0)}
    engine = RiskEngine(RiskLimits(max_add_to_loser_pct=0.05))
    order = ProposedOrder(symbol="AAA", side="buy", shares=10, price=90.0)

    decision = engine.evaluate([order], make_portfolio(positions))

    assert decision.approved_orders == []
    assert "martingale" in decision.vetoed_orders[0].reason.lower()


def test_allows_adding_to_a_position_within_threshold():
    # Down only 2%, threshold is 5% -- not yet a martingale-style add.
    positions = {"AAA": Position(symbol="AAA", shares=100, avg_cost=100.0, current_price=98.0)}
    engine = RiskEngine(RiskLimits(max_add_to_loser_pct=0.05))
    order = ProposedOrder(symbol="AAA", side="buy", shares=10, price=98.0)

    decision = engine.evaluate([order], make_portfolio(positions))

    assert len(decision.approved_orders) == 1


def test_allows_adding_to_a_winning_position():
    # max_position_pct set generously so it can't be what blocks this order --
    # this test isolates the anti-martingale rule specifically.
    positions = {"AAA": Position(symbol="AAA", shares=100, avg_cost=100.0, current_price=120.0)}
    engine = RiskEngine(RiskLimits(max_add_to_loser_pct=0.05, max_position_pct=1.0))
    order = ProposedOrder(symbol="AAA", side="buy", shares=10, price=120.0)

    decision = engine.evaluate([order], make_portfolio(positions))

    assert len(decision.approved_orders) == 1


def test_opening_a_brand_new_position_is_never_blocked_by_martingale_rule():
    # No existing position in BBB at all -- there's nothing to "double down" on.
    positions = {"AAA": Position(symbol="AAA", shares=100, avg_cost=100.0, current_price=50.0)}
    engine = RiskEngine(RiskLimits(max_add_to_loser_pct=0.05))
    order = ProposedOrder(symbol="BBB", side="buy", shares=10, price=50.0)

    decision = engine.evaluate([order], make_portfolio(positions))

    assert len(decision.approved_orders) == 1
