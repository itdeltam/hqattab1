from app.risk.engine import RiskEngine
from app.risk.limits import RiskLimits
from app.risk.models import PortfolioState, Position, ProposedOrder


def test_buy_allowed_when_no_limits_breached():
    portfolio = PortfolioState(
        equity=100_000, day_start_equity=100_000, week_start_equity=100_000, peak_equity=100_000,
    )
    engine = RiskEngine(RiskLimits(max_daily_loss_pct=0.02))
    order = ProposedOrder(symbol="AAA", side="buy", shares=10, price=100.0)

    decision = engine.evaluate([order], portfolio)

    assert decision.approved_orders == [order]
    assert decision.kill_switch_engaged is False


def test_daily_loss_limit_blocks_buys():
    # Equity down 3% intraday from day-start; limit is 2%.
    portfolio = PortfolioState(
        equity=97_000, day_start_equity=100_000, week_start_equity=100_000, peak_equity=100_000,
    )
    engine = RiskEngine(RiskLimits(max_daily_loss_pct=0.02))
    order = ProposedOrder(symbol="AAA", side="buy", shares=10, price=100.0)

    decision = engine.evaluate([order], portfolio)

    assert decision.approved_orders == []
    assert any("Daily loss limit" in n for n in decision.notes)


def test_daily_loss_limit_does_not_block_sells():
    positions = {"AAA": Position(symbol="AAA", shares=10, avg_cost=100.0, current_price=97.0)}
    portfolio = PortfolioState(
        equity=97_000, day_start_equity=100_000, week_start_equity=100_000, peak_equity=100_000,
        positions=positions,
    )
    engine = RiskEngine(RiskLimits(max_daily_loss_pct=0.02))
    order = ProposedOrder(symbol="AAA", side="sell", shares=10, price=97.0)

    decision = engine.evaluate([order], portfolio)

    assert decision.approved_orders == [order]


def test_weekly_loss_limit_blocks_buys():
    portfolio = PortfolioState(
        equity=94_000, day_start_equity=95_000, week_start_equity=100_000, peak_equity=100_000,
    )
    engine = RiskEngine(RiskLimits(max_daily_loss_pct=0.5, max_weekly_loss_pct=0.05))
    order = ProposedOrder(symbol="AAA", side="buy", shares=10, price=100.0)

    decision = engine.evaluate([order], portfolio)

    assert decision.approved_orders == []
    assert any("Weekly loss limit" in n for n in decision.notes)


def test_drawdown_kill_switch_engages_and_blocks_buys():
    # 20% drawdown from peak; limit is 15%.
    portfolio = PortfolioState(
        equity=80_000, day_start_equity=80_000, week_start_equity=80_000, peak_equity=100_000,
    )
    engine = RiskEngine(RiskLimits(max_drawdown_pct=0.15))
    order = ProposedOrder(symbol="AAA", side="buy", shares=10, price=100.0)

    decision = engine.evaluate([order], portfolio)

    assert decision.kill_switch_engaged is True
    assert decision.approved_orders == []


def test_drawdown_kill_switch_does_not_block_sells():
    positions = {"AAA": Position(symbol="AAA", shares=10, avg_cost=100.0, current_price=80.0)}
    portfolio = PortfolioState(
        equity=80_000, day_start_equity=80_000, week_start_equity=80_000, peak_equity=100_000,
        positions=positions,
    )
    engine = RiskEngine(RiskLimits(max_drawdown_pct=0.15))
    order = ProposedOrder(symbol="AAA", side="sell", shares=10, price=80.0)

    decision = engine.evaluate([order], portfolio)

    assert decision.kill_switch_engaged is True
    assert decision.approved_orders == [order]


def test_no_drawdown_when_equity_at_peak():
    portfolio = PortfolioState(
        equity=100_000, day_start_equity=100_000, week_start_equity=100_000, peak_equity=100_000,
    )
    engine = RiskEngine(RiskLimits(max_drawdown_pct=0.15))

    decision = engine.evaluate([], portfolio)

    assert decision.kill_switch_engaged is False
