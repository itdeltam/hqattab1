"""The Risk Engine: a pure, stateless gatekeeper the Strategy's proposed
orders must pass through before they ever reach the Order Manager. Per the
project's non-negotiable safety rules, this module can veto or clip any
proposed trade -- there is no "the strategy is confident" override, and
nothing in ProposedOrder.metadata can change a decision here.

evaluate() takes a full PortfolioState snapshot and returns a full
decision every time; it holds no internal state between calls. That keeps
it trivially unit-testable and means the caller (the future Trading
Engine, Stage 6) owns all persistence -- e.g. whether a triggered drawdown
kill switch requires a human to acknowledge it before trading resumes is a
Stage 6 concern, not something baked into this stateless evaluate() call.
"""
from __future__ import annotations

from app.risk.limits import RiskLimits
from app.risk.models import PortfolioState, ProposedOrder, RiskDecision, VetoedOrder

_EPSILON = 1e-9


class RiskEngine:
    def __init__(self, limits: RiskLimits):
        self.limits = limits

    def evaluate(self, proposed_orders: list[ProposedOrder], portfolio: PortfolioState) -> RiskDecision:
        approved: list[ProposedOrder] = []
        vetoed: list[VetoedOrder] = []
        notes: list[str] = []

        kill_switch = self._drawdown_kill_switch_triggered(portfolio)
        if kill_switch:
            notes.append(
                f"Drawdown kill switch engaged: equity {portfolio.equity:,.2f} is more than "
                f"{self.limits.max_drawdown_pct:.1%} below peak {portfolio.peak_equity:,.2f}. "
                "All new risk-increasing orders blocked."
            )

        daily_halt = self._loss_limit_breached(
            portfolio.equity, portfolio.day_start_equity, self.limits.max_daily_loss_pct
        )
        weekly_halt = self._loss_limit_breached(
            portfolio.equity, portfolio.week_start_equity, self.limits.max_weekly_loss_pct
        )
        if daily_halt:
            notes.append("Daily loss limit breached: all new risk-increasing orders blocked.")
        if weekly_halt:
            notes.append("Weekly loss limit breached: all new risk-increasing orders blocked.")

        trading_halted = kill_switch or daily_halt or weekly_halt

        # Running exposure, updated as orders are approved/clipped in
        # sequence so that e.g. two buys in the same batch for correlated
        # symbols are evaluated against each other, not just against the
        # portfolio snapshot from before this batch started.
        position_values = {s: p.market_value for s, p in portfolio.positions.items()}

        for order in proposed_orders:
            if order.side == "sell":
                decision = self._evaluate_sell(order, portfolio)
            else:
                decision = self._evaluate_buy(order, portfolio, position_values, trading_halted)

            if isinstance(decision, VetoedOrder):
                vetoed.append(decision)
                continue

            approved_order = decision
            if approved_order.shares != order.shares:
                notes.append(
                    f"Clipped {order.symbol} {order.side} from {order.shares:.4f} to "
                    f"{approved_order.shares:.4f} shares."
                )
            position_values[approved_order.symbol] = position_values.get(approved_order.symbol, 0.0) + (
                approved_order.notional if approved_order.side == "buy" else -approved_order.notional
            )
            approved.append(approved_order)

        return RiskDecision(
            approved_orders=approved, vetoed_orders=vetoed, kill_switch_engaged=kill_switch, notes=notes,
        )

    def _evaluate_sell(self, order: ProposedOrder, portfolio: PortfolioState):
        # Long-only, no exceptions: a sell can never exceed the shares
        # actually held, which would open a short position.
        held = portfolio.positions.get(order.symbol)
        held_shares = held.shares if held else 0.0
        if order.shares > held_shares + _EPSILON:
            return VetoedOrder(
                order,
                f"Refusing to sell {order.shares:.4f} shares of {order.symbol}: only "
                f"{held_shares:.4f} held. This system is long-only and never shorts.",
            )
        # Sells always reduce risk -- never blocked by loss limits, the
        # kill switch, position/leverage caps, or the anti-martingale rule.
        return order

    def _evaluate_buy(
        self,
        order: ProposedOrder,
        portfolio: PortfolioState,
        position_values: dict[str, float],
        trading_halted: bool,
    ):
        if trading_halted:
            return VetoedOrder(order, "Trading halted (loss limit or drawdown kill switch active).")

        existing = portfolio.positions.get(order.symbol)
        if existing and existing.unrealized_pnl_pct <= -self.limits.max_add_to_loser_pct:
            return VetoedOrder(
                order,
                f"Refusing to add to {order.symbol}: already down "
                f"{existing.unrealized_pnl_pct:.1%}, exceeds the no-martingale threshold "
                f"of {self.limits.max_add_to_loser_pct:.1%}.",
            )

        remaining_shares = order.shares

        remaining_shares, veto_reason = self._clip_to_position_limit(
            order.symbol, remaining_shares, order.price, position_values, portfolio.equity,
        )
        if veto_reason:
            return VetoedOrder(order, veto_reason)

        remaining_shares, veto_reason = self._clip_to_leverage_limit(
            remaining_shares, order.price, position_values, portfolio.equity,
        )
        if veto_reason:
            return VetoedOrder(order, veto_reason)

        veto_reason = self._check_correlation_limit(
            order.symbol, remaining_shares, order.price, position_values, portfolio,
        )
        if veto_reason:
            return VetoedOrder(order, veto_reason)

        return order.with_shares(remaining_shares)

    def _clip_to_position_limit(
        self, symbol: str, shares: float, price: float,
        position_values: dict[str, float], equity: float,
    ) -> tuple[float, str | None]:
        current_value = position_values.get(symbol, 0.0)
        max_value = self.limits.max_position_pct * equity
        headroom = max_value - current_value

        if headroom <= _EPSILON:
            return 0.0, (
                f"{symbol} already at or above the {self.limits.max_position_pct:.1%} "
                "max-position-size limit."
            )

        proposed_value = shares * price
        if proposed_value <= headroom:
            return shares, None
        return headroom / price, None

    def _clip_to_leverage_limit(
        self, shares: float, price: float,
        position_values: dict[str, float], equity: float,
    ) -> tuple[float, str | None]:
        max_gross = equity * self.limits.max_leverage if self.limits.allow_leverage else equity
        current_gross = sum(position_values.values())
        headroom = max_gross - current_gross

        if headroom <= _EPSILON:
            return 0.0, "No leverage headroom remaining (no-leverage cap reached)."

        proposed_value = shares * price
        if proposed_value <= headroom:
            return shares, None
        return headroom / price, None

    def _check_correlation_limit(
        self, symbol: str, shares: float, price: float,
        position_values: dict[str, float], portfolio: PortfolioState,
    ) -> str | None:
        if not portfolio.correlations or shares <= 0:
            return None

        equity = portfolio.equity
        projected_value = position_values.get(symbol, 0.0) + shares * price
        pair_correlations = portfolio.correlations.get(symbol, {})

        for other_symbol, other_value in position_values.items():
            if other_symbol == symbol or other_value <= 0:
                continue
            correlation = pair_correlations.get(other_symbol)
            if correlation is None or correlation < self.limits.max_correlation:
                continue
            combined_pct = (projected_value + other_value) / equity
            if combined_pct > self.limits.max_correlated_group_pct:
                return (
                    f"{symbol} and {other_symbol} are correlated at {correlation:.2f} "
                    f"(>= {self.limits.max_correlation:.2f}); combined weight would reach "
                    f"{combined_pct:.1%}, over the {self.limits.max_correlated_group_pct:.1%} cap."
                )
        return None

    def _loss_limit_breached(self, equity: float, period_start_equity: float, limit_pct: float) -> bool:
        if period_start_equity <= 0:
            return False
        loss_pct = (period_start_equity - equity) / period_start_equity
        return loss_pct >= limit_pct

    def _drawdown_kill_switch_triggered(self, portfolio: PortfolioState) -> bool:
        if portfolio.peak_equity <= 0:
            return False
        drawdown_pct = (portfolio.peak_equity - portfolio.equity) / portfolio.peak_equity
        return drawdown_pct >= self.limits.max_drawdown_pct
