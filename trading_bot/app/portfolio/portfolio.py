"""Bridges the broker (authoritative for positions/cash/equity) and the
database (authoritative for history: equity over time, needed for the
Risk Engine's day/week-start and peak-equity calculations) into the
PortfolioState snapshot the Risk Engine needs. Portfolio never keeps its
own ledger of positions or cash -- it always reads the broker fresh, so
it can never itself drift out of sync with broker truth.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from sqlalchemy.orm import Session

from app.broker.paper import PaperBroker
from app.database.repository import (
    get_day_start_equity,
    get_peak_equity,
    get_week_start_equity,
    record_equity_snapshot,
)
from app.risk.models import PortfolioState, Position

PriceLookup = Callable[[str], "float | None"]


class Portfolio:
    def __init__(self, broker: PaperBroker, session: Session, price_lookup: PriceLookup):
        self.broker = broker
        self.session = session
        self._price_lookup = price_lookup

    def record_equity_snapshot(self, now: datetime) -> None:
        account = self.broker.get_account()
        record_equity_snapshot(self.session, now, account.equity, account.cash)

    def current_state(
        self,
        now: datetime,
        correlations: dict[str, dict[str, float]] | None = None,
    ) -> PortfolioState:
        account = self.broker.get_account()
        broker_positions = self.broker.get_positions()

        positions = {
            symbol: Position(
                symbol=symbol,
                shares=position.qty,
                avg_cost=position.avg_entry_price,
                current_price=self._price_lookup(symbol) or position.avg_entry_price,
            )
            for symbol, position in broker_positions.items()
        }

        day_start_equity = get_day_start_equity(self.session, now)
        week_start_equity = get_week_start_equity(self.session, now)
        peak_equity = get_peak_equity(self.session)

        return PortfolioState(
            equity=account.equity,
            day_start_equity=day_start_equity if day_start_equity is not None else account.equity,
            week_start_equity=week_start_equity if week_start_equity is not None else account.equity,
            peak_equity=max(peak_equity, account.equity) if peak_equity is not None else account.equity,
            positions=positions,
            correlations=correlations,
        )
