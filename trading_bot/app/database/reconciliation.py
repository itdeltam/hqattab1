"""Startup reconciliation. Non-negotiable project rule: on every startup,
local DB state is reconciled against the broker's actual account,
positions, and orders before any trading is allowed. Broker state is
always authoritative -- this module never merges or negotiates, it
overwrites local state with whatever the broker reports and logs every
discrepancy found so it's visible (Stage 8 will wire this into alerts).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.broker.paper import PaperBroker
from app.database.repository import (
    get_all_order_ids,
    get_all_positions,
    get_open_orders,
    record_equity_snapshot,
    replace_all_positions,
    upsert_order,
)

_EPSILON = 1e-9

# How far back to look for broker orders missing from the local DB
# entirely (see the "recovered" loop below). Bounded rather than scanning
# full account history on every startup -- a crash between an order
# reaching the broker and being persisted locally is a same-session event,
# not something that could be days old.
_ORDER_RECOVERY_LOOKBACK = timedelta(days=1)


@dataclass(frozen=True)
class ReconciliationReport:
    positions_before: dict[str, float]
    positions_after: dict[str, float]
    orders_resynced: list[str]
    discrepancies: list[str]
    orders_recovered: list[str] = field(default_factory=list)

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

    # Orders that reached the broker but were never recorded locally at
    # all -- e.g. the process crashed between broker.submit_order()
    # succeeding and the DB write that would have persisted it. The
    # open-orders resync above can't find these: it only looks up ids the
    # local DB already knows about. Position reconciliation above already
    # self-heals from this (broker positions always win regardless), but
    # the order audit trail would otherwise be silently lost forever.
    known_ids = get_all_order_ids(session)
    orders_recovered = []
    for broker_order in broker.list_orders(since=now - _ORDER_RECOVERY_LOOKBACK):
        if broker_order.id in known_ids:
            continue
        upsert_order(session, broker_order, now)
        orders_recovered.append(broker_order.id)
        discrepancies.append(
            f"Order {broker_order.id} existed on the broker but was missing from local DB -- recovered"
        )

    account = broker.get_account()
    record_equity_snapshot(session, now, account.equity, account.cash)

    return ReconciliationReport(
        positions_before={s: p.qty for s, p in local_positions.items()},
        positions_after={s: p.qty for s, p in broker_positions.items()},
        orders_resynced=orders_resynced,
        discrepancies=discrepancies,
        orders_recovered=orders_recovered,
    )
