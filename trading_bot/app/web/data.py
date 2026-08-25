"""Read-only view-model queries backing the dashboard. Every function here
does exactly one thing: read from the database and shape the result for a
template. None of them, anywhere in this module, write anything -- that
split is what makes the "the dashboard never mutates trading state" claim
checkable by reading this file alone, not just by inspecting routes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import EquitySnapshot, OrderRecord, PositionRecord
from app.monitoring.heartbeat import DEFAULT_HEARTBEAT_COMPONENT, get_heartbeat, is_stale


@dataclass(frozen=True)
class AccountSummary:
    equity: float | None
    cash: float | None
    as_of: datetime | None

    @property
    def has_data(self) -> bool:
        return self.as_of is not None


@dataclass(frozen=True)
class PositionView:
    symbol: str
    qty: float
    avg_entry_price: float
    cost_basis: float
    updated_at: datetime


@dataclass(frozen=True)
class SystemStatus:
    trading_mode: str
    last_activity: datetime | None
    seconds_since_activity: float | None
    last_heartbeat: datetime | None
    heartbeat_healthy: bool


def get_account_summary(session: Session) -> AccountSummary:
    row = session.scalars(
        select(EquitySnapshot).order_by(EquitySnapshot.timestamp.desc()).limit(1)
    ).first()
    if row is None:
        return AccountSummary(equity=None, cash=None, as_of=None)
    return AccountSummary(equity=row.equity, cash=row.cash, as_of=row.timestamp)


def get_positions_view(session: Session) -> list[PositionView]:
    rows = session.scalars(select(PositionRecord).order_by(PositionRecord.symbol)).all()
    return [
        PositionView(
            symbol=r.symbol, qty=r.qty, avg_entry_price=r.avg_entry_price,
            cost_basis=r.qty * r.avg_entry_price, updated_at=r.updated_at,
        )
        for r in rows
    ]


def get_recent_orders(session: Session, limit: int = 20) -> list[OrderRecord]:
    return list(session.scalars(
        select(OrderRecord).order_by(OrderRecord.submitted_at.desc()).limit(limit)
    ).all())


def get_system_status(
    session: Session,
    trading_mode: str,
    now: datetime,
    heartbeat_stale_seconds: float = 120.0,
) -> SystemStatus:
    latest_equity = session.scalars(
        select(EquitySnapshot.timestamp).order_by(EquitySnapshot.timestamp.desc()).limit(1)
    ).first()
    latest_order = session.scalars(
        select(OrderRecord.updated_at).order_by(OrderRecord.updated_at.desc()).limit(1)
    ).first()

    candidates = [t for t in (latest_equity, latest_order) if t is not None]
    last_activity = max(candidates) if candidates else None
    seconds_since = (now - last_activity).total_seconds() if last_activity else None

    # Heartbeat is a separate liveness signal from "traded activity" -- it
    # should keep landing on days the strategy does nothing (market closed,
    # nothing eligible), so it can tell "alive but idle" apart from
    # "crashed or hung" in a way last_activity alone cannot.
    heartbeat_record = get_heartbeat(session, DEFAULT_HEARTBEAT_COMPONENT)
    last_heartbeat = heartbeat_record.last_beat_at if heartbeat_record else None
    heartbeat_healthy = not is_stale(last_heartbeat, now, heartbeat_stale_seconds)

    return SystemStatus(
        trading_mode=trading_mode,
        last_activity=last_activity,
        seconds_since_activity=seconds_since,
        last_heartbeat=last_heartbeat,
        heartbeat_healthy=heartbeat_healthy,
    )
