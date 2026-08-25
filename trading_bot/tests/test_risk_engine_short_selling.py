from app.risk.engine import RiskEngine
from app.risk.limits import RiskLimits
from app.risk.models import PortfolioState, Position, ProposedOrder


def make_portfolio(equity=100_000.0, positions=None):
    return PortfolioState(
        equity=equity, day_start_equity=equity, week_start_equity=equity,
        peak_equity=equity, positions=positions or {},
    )


def test_sell_within_held_shares_is_approved():
    positions = {"AAA": Position(symbol="AAA", shares=100, avg_cost=90.0, current_price=100.0)}
    engine = RiskEngine(RiskLimits())
    order = ProposedOrder(symbol="AAA", side="sell", shares=50, price=100.0)

    decision = engine.evaluate([order], make_portfolio(positions=positions))

    assert decision.approved_orders == [order]


def test_sell_exceeding_held_shares_is_vetoed_never_shorts():
    positions = {"AAA": Position(symbol="AAA", shares=50, avg_cost=90.0, current_price=100.0)}
    engine = RiskEngine(RiskLimits())
    order = ProposedOrder(symbol="AAA", side="sell", shares=100, price=100.0)

    decision = engine.evaluate([order], make_portfolio(positions=positions))

    assert decision.approved_orders == []
    assert "long-only" in decision.vetoed_orders[0].reason.lower()


def test_sell_of_symbol_never_held_is_vetoed():
    engine = RiskEngine(RiskLimits())
    order = ProposedOrder(symbol="AAA", side="sell", shares=1, price=100.0)

    decision = engine.evaluate([order], make_portfolio())

    assert decision.approved_orders == []


def test_sell_exactly_all_held_shares_is_approved():
    positions = {"AAA": Position(symbol="AAA", shares=50, avg_cost=90.0, current_price=100.0)}
    engine = RiskEngine(RiskLimits())
    order = ProposedOrder(symbol="AAA", side="sell", shares=50, price=100.0)

    decision = engine.evaluate([order], make_portfolio(positions=positions))

    assert decision.approved_orders == [order]
