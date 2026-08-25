"""Startup reconciliation. Non-negotiable project rule: on every startup,
local DB state is reconciled against the broker's actual account,
positions, and orders before any trading is allowed. Broker state is
always authoritative -- this module never merges or negotiates, it
overwrites local state with whatever the broker reports and logs every
discrepancy found so it's visible (Stage 8 will wire this into alerts).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.broker.paper import PaperBroker
from app.database.repository import (
    get_all_positions,
    get_open_orders,
    record_equity_snapshot,
    replace_all_positions,
    upsert_order,
)

_EPSILON = 1e-9


@dataclass(frozen=True)
class ReconciliationReport:
    positions_before: dict[str, float]
    positions_after: dict[str, float]
    orders_resynced: list[str]
    discrepancies: list[str]

    @property
    def is_clean(self) -> bool:
        return not self.discrepancies


def reconcile_startup_state(broker: PaperBroker, session: Session, now: datetime) -> ReconciliationReport:
    local_positions = get_all_positions(session)
    broker_positions = broker.get_positions()

    discrepancies = []
    for symbol in set(local_positions) | set(broker_positions):
        local_qty = local_positions[symbol].qty if symbol in local_positions else 0.0
        broker_qty = broker_positions[symbol].qty if symbol in broker_positions else 0.0
        if abs(local_qty - broker_qty) > _EPSILON:
            discrepancies.append(
                f"{symbol}: local DB had {local_qty}, broker reports {broker_qty} -- broker wins"
            )

    replace_all_positions(session, broker_positions, now)

    orders_resynced = []
    for order_record in get_open_orders(session):
        try:
            broker_order = broker.get_order(order_record.id)
        except KeyError:
            discrepancies.append(
                f"Order {order_record.id} was open in local DB but is unknown to the broker"
            )
            continue

        if broker_order.status.value != order_record.status:
            discrepancies.append(
                f"Order {order_record.id}: local DB had status {order_record.status}, "
                f"broker reports {broker_order.status.value} -- broker wins"
            )
        upsert_order(session, broker_order, now)
        orders_resynced.append(order_record.id)

    account = broker.get_account()
    record_equity_snapshot(session, now, account.equity, account.cash)

    return ReconciliationReport(
        positions_before={s: p.qty for s, p in local_positions.items()},
        positions_after={s: p.qty for s, p in broker_positions.items()},
        orders_resynced=orders_resynced,
        discrepancies=discrepancies,
    )
