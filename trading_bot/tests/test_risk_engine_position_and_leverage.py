import pytest

from app.risk.engine import RiskEngine
from app.risk.limits import RiskLimits
from app.risk.models import PortfolioState, ProposedOrder


def make_portfolio(equity=100_000.0, positions=None, **overrides):
    defaults = dict(day_start_equity=equity, week_start_equity=equity, peak_equity=equity)
    defaults.update(overrides)
    return PortfolioState(equity=equity, positions=positions or {}, **defaults)


def test_buy_within_position_limit_is_approved_unchanged():
    engine = RiskEngine(RiskLimits(max_position_pct=0.10))
    order = ProposedOrder(symbol="AAA", side="buy", shares=50, price=100.0)  # $5,000 of $100,000 = 5%

    decision = engine.evaluate([order], make_portfolio())

    assert decision.approved_orders == [order]
    assert decision.vetoed_orders == []


def test_buy_exceeding_position_limit_is_clipped():
    engine = RiskEngine(RiskLimits(max_position_pct=0.10))
    # 200 shares @ $100 = $20,000 = 20% of $100,000 equity -- double the 10% cap.
    order = ProposedOrder(symbol="AAA", side="buy", shares=200, price=100.0)

    decision = engine.evaluate([order], make_portfolio())

    assert len(decision.approved_orders) == 1
    approved = decision.approved_orders[0]
    assert approved.shares == pytest.approx(100.0)  # $10,000 / $100 = 100 shares = 10% cap
    assert decision.vetoed_orders == []


def test_buy_when_already_at_cap_is_fully_vetoed():
    engine = RiskEngine(RiskLimits(max_position_pct=0.10))
    from app.risk.models import Position
    positions = {"AAA": Position(symbol="AAA", shares=100, avg_cost=100.0, current_price=100.0)}
    order = ProposedOrder(symbol="AAA", side="buy", shares=10, price=100.0)

    decision = engine.evaluate([order], make_portfolio(positions=positions))

    assert decision.approved_orders == []
    assert len(decision.vetoed_orders) == 1
    assert "max-position-size" in decision.vetoed_orders[0].reason


def test_buy_within_default_no_leverage_cap_is_approved():
    engine = RiskEngine(RiskLimits(max_position_pct=1.0, allow_leverage=False))
    order = ProposedOrder(symbol="AAA", side="buy", shares=1000, price=100.0)  # exactly 100% of equity

    decision = engine.evaluate([order], make_portfolio())

    assert decision.approved_orders[0].shares == pytest.approx(1000.0)


def test_buy_exceeding_no_leverage_cap_is_clipped():
    engine = RiskEngine(RiskLimits(max_position_pct=1.0, allow_leverage=False))
    order = ProposedOrder(symbol="AAA", side="buy", shares=1500, price=100.0)  # 150% of equity

    decision = engine.evaluate([order], make_portfolio())

    assert decision.approved_orders[0].shares == pytest.approx(1000.0)  # clipped to 100%


def test_leverage_allowed_when_explicitly_enabled():
    # max_position_pct set above max_leverage so the per-symbol cap doesn't
    # bind first -- this test isolates the leverage check specifically.
    engine = RiskEngine(RiskLimits(max_position_pct=2.0, allow_leverage=True, max_leverage=2.0))
    order = ProposedOrder(symbol="AAA", side="buy", shares=1500, price=100.0)  # 150% of equity

    decision = engine.evaluate([order], make_portfolio())

    assert decision.approved_orders[0].shares == pytest.approx(1500.0)


def test_leverage_still_capped_at_configured_max_even_when_enabled():
    engine = RiskEngine(RiskLimits(max_position_pct=2.0, allow_leverage=True, max_leverage=1.5))
    order = ProposedOrder(symbol="AAA", side="buy", shares=2000, price=100.0)  # 200% of equity

    decision = engine.evaluate([order], make_portfolio())

    assert decision.approved_orders[0].shares == pytest.approx(1500.0)  # clipped to 150%
