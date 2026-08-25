"""Plain data-access functions over a SQLAlchemy Session. Deliberately
just functions, not a repository class hierarchy -- there's one shape of
each record and one database, no need for the extra ceremony."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.broker.models import BrokerPosition, Order
from app.database.models import EquitySnapshot, OrderRecord, PositionRecord


def replace_all_positions(session: Session, positions: dict[str, BrokerPosition], now: datetime) -> None:
    """Full overwrite from broker truth -- never a partial diff. See the
    module docstring in app/database/models.py for why."""
    session.query(PositionRecord).delete()
    for symbol, position in positions.items():
        session.add(PositionRecord(
            symbol=symbol, qty=position.qty, avg_entry_price=position.avg_entry_price, updated_at=now,
        ))
    session.commit()


def get_all_positions(session: Session) -> dict[str, PositionRecord]:
    records = session.scalars(select(PositionRecord)).all()
    return {r.symbol: r for r in records}


def upsert_order(session: Session, order: Order, now: datetime) -> None:
    existing = session.get(OrderRecord, order.id)
    if existing is None:
        existing = OrderRecord(id=order.id, submitted_at=order.submitted_at)
        session.add(existing)

    existing.symbol = order.request.symbol
    existing.side = order.request.side.value
    existing.qty = order.request.qty
    existing.status = order.status.value
    existing.filled_qty = order.filled_qty
    existing.avg_fill_price = order.avg_fill_price
    existing.rejection_reason = order.rejection_reason
    existing.updated_at = now
    session.commit()


def get_open_orders(session: Session) -> list[OrderRecord]:
    return list(session.scalars(
        select(OrderRecord).where(OrderRecord.status.in_(["new", "partially_filled"]))
    ).all())


def record_equity_snapshot(session: Session, now: datetime, equity: float, cash: float) -> None:
    session.add(EquitySnapshot(timestamp=now, equity=equity, cash=cash))
    session.commit()


def get_day_start_equity(session: Session, now: datetime) -> float | None:
    day_start = datetime(now.year, now.month, now.day)
    row = session.scalars(
        select(EquitySnapshot)
        .where(EquitySnapshot.timestamp >= day_start)
        .order_by(EquitySnapshot.timestamp.asc())
        .limit(1)
    ).first()
    return row.equity if row else None


def get_week_start_equity(session: Session, now: datetime) -> float | None:
    week_start_date = now.date() - timedelta(days=now.weekday())  # Monday
    week_start = datetime(week_start_date.year, week_start_date.month, week_start_date.day)
    row = session.scalars(
        select(EquitySnapshot)
        .where(EquitySnapshot.timestamp >= week_start)
        .order_by(EquitySnapshot.timestamp.asc())
        .limit(1)
    ).first()
    return row.equity if row else None


def get_peak_equity(session: Session) -> float | None:
    rows = session.scalars(select(EquitySnapshot.equity)).all()
    return max(rows) if rows else None
