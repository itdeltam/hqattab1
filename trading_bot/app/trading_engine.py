"""Wires Strategy -> Portfolio -> Risk Engine -> Order Manager -> Broker
into one cycle, with mandatory startup reconciliation. This is
orchestration only -- every piece it calls (signals, selection, sizing,
risk rules, broker mechanics) is already independently built and tested
in its own module; this file's job is to connect them in the right order
and never skip a step.

Two non-negotiable properties enforced here, not just documented:
1. reconcile_on_startup() must run before run_rebalance_cycle() is ever
   called -- see app/main.py for how that's sequenced.
2. Every order that reaches the broker has passed through RiskEngine's
   evaluate() first. There is no path from a Strategy decision to
   OrderManager that skips the Risk Engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

import pandas as pd
from sqlalchemy.orm import Session

from app.alerts.events import AlertEvent, Severity
from app.alerts.manager import AlertManager
from app.broker.models import Order
from app.broker.paper import PaperBroker
from app.database.reconciliation import ReconciliationReport, reconcile_startup_state
from app.execution.order_manager import OrderManager
from app.monitoring.heartbeat import DEFAULT_HEARTBEAT_COMPONENT, record_heartbeat
from app.portfolio.portfolio import Portfolio
from app.risk.engine import RiskEngine
from app.risk.models import ProposedOrder, RiskDecision
from app.strategy.params import StrategyParams
from app.strategy.rebalancing import compute_order_deltas, compute_target_weights
from app.strategy.signals import momentum_score, realized_vol, trend_filter

PriceLookup = Callable[[str], "float | None"]


@dataclass(frozen=True)
class CycleResult:
    target_weights: dict[str, float]
    selected: set[str]
    proposed_orders: list[ProposedOrder]
    risk_decision: RiskDecision
    submitted_orders: list[Order]


@dataclass
class TradingEngine:
    broker: PaperBroker
    session: Session
    risk_engine: RiskEngine
    strategy_params: StrategyParams
    price_lookup: PriceLookup
    alert_manager: AlertManager = field(default_factory=lambda: AlertManager(sinks=[]))
    heartbeat_component: str = DEFAULT_HEARTBEAT_COMPONENT
    portfolio: Portfolio = field(init=False)
    order_manager: OrderManager = field(init=False)

    def __post_init__(self) -> None:
        self.portfolio = Portfolio(self.broker, self.session, self.price_lookup)
        self.order_manager = OrderManager(self.broker, self.session)

    def heartbeat(self, now: datetime) -> None:
        """Records liveness independent of whether a rebalance cycle ran.
        Intended to be called on a tight, fixed cadence (e.g. every
        scheduler tick) by whatever runs this engine, so the dashboard can
        tell "alive but idle" apart from "crashed or hung" (see
        app/monitoring/heartbeat.py)."""
        record_heartbeat(self.session, self.heartbeat_component, now)

    def reconcile_on_startup(self, now: datetime) -> ReconciliationReport:
        """Must be called once, before run_rebalance_cycle is ever called.
        Broker state overwrites local DB state unconditionally. Any
        discrepancy found is surfaced as an alert -- it means local state
        drifted from broker truth (e.g. a crash mid-cycle), which is worth
        a human's attention even though it self-heals automatically."""
        report = reconcile_startup_state(self.broker, self.session, now)
        self.heartbeat(now)
        if not report.is_clean:
            self.alert_manager.notify(AlertEvent(
                severity=Severity.WARNING,
                title="Startup reconciliation found discrepancies",
                detail="; ".join(report.discrepancies),
                timestamp=now,
            ))
        return report

    def poll_fills(self, now: datetime) -> list[Order]:
        return self.order_manager.poll_fills(now)

    def run_rebalance_cycle(
        self,
        now: datetime,
        price_history: pd.DataFrame,
        current_prices: dict[str, float],
        correlations: dict[str, dict[str, float]] | None = None,
    ) -> CycleResult:
        """One full rebalance decision. `price_history` is close prices
        through the *prior* session only (no-look-ahead, same discipline
        as the backtester) -- signals are computed from it. `current_prices`
        is today's live quote, used both for order notional (what the Risk
        Engine reasons about) and for the Risk Engine's mark-to-market of
        existing positions.
        """
        params = self.strategy_params

        self.heartbeat(now)
        self.portfolio.record_equity_snapshot(now)
        portfolio_state = self.portfolio.current_state(now, correlations=correlations)

        eligible = price_history.apply(lambda s: trend_filter(s, params))
        scores = price_history.apply(lambda s: momentum_score(s, params))
        vols = price_history.apply(lambda s: realized_vol(s, params.vol_window))
        latest = price_history.index[-1]

        current_momentum_holdings = {
            symbol for symbol in portfolio_state.positions if symbol != params.defensive_asset
        }

        weights, selected = compute_target_weights(
            eligible.loc[latest], scores.loc[latest], vols.loc[latest],
            current_momentum_holdings, params,
        )

        current_shares = {
            symbol: portfolio_state.positions[symbol].shares if symbol in portfolio_state.positions else 0.0
            for symbol in price_history.columns
        }
        deltas = compute_order_deltas(weights, current_shares, price_history.loc[latest], portfolio_state.equity)

        proposed_orders = [
            ProposedOrder(
                symbol=symbol,
                side="buy" if delta > 0 else "sell",
                shares=abs(delta),
                price=current_prices.get(symbol, price_history.loc[latest, symbol]),
            )
            for symbol, delta in deltas.items()
        ]

        risk_decision = self.risk_engine.evaluate(proposed_orders, portfolio_state)
        submitted = self.order_manager.submit_approved_orders(risk_decision.approved_orders, now)

        return CycleResult(
            target_weights=weights, selected=selected, proposed_orders=proposed_orders,
            risk_decision=risk_decision, submitted_orders=submitted,
        )
