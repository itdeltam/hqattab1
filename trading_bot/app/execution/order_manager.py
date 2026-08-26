"""Translates Risk-Engine-approved orders into broker submissions, and
keeps the database's order records in sync with the broker's view of
those orders. Never resubmits a rejected order on its own -- a rejection
is recorded and surfaced; retrying is a deliberate future decision, not a
silent default.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.broker.models import Order, OrderRequest, OrderSide
from app.broker.paper import PaperBroker
from app.database.repository import upsert_order
from app.risk.models import ProposedOrder


class OrderManager:
    def __init__(self, broker: PaperBroker, session: Session):
        self.broker = broker
        self.session = session

    def submit_approved_orders(self, approved_orders: list[ProposedOrder], now: datetime) -> list[Order]:
        submitted = []
        for order in approved_orders:
            side = OrderSide.BUY if order.side == "buy" else OrderSide.SELL
            request = OrderRequest(symbol=order.symbol, side=side, qty=order.shares)
            broker_order = self.broker.submit_order(request, now)
            upsert_order(self.session, broker_order, now)
            submitted.append(broker_order)
        return submitted

    def poll_fills(self, now: datetime) -> list[Order]:
        updated = self.broker.advance_time(now)
        for order in updated:
            upsert_order(self.session, order, now)
        return updated
