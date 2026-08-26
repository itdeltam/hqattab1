"""SQLAlchemy models. This database is a *mirror* of broker truth, never
an independent ledger -- positions and orders here are always overwritten
from what the broker reports (see app/database/reconciliation.py), so the
DB can never drift out of sync with the account that actually holds the
money. What it uniquely owns is history: equity snapshots over time,
needed to derive day/week-start equity and peak equity for the Risk
Engine, and an audit trail of orders across restarts.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PositionRecord(Base):
    __tablename__ = "positions"

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    qty: Mapped[float] = mapped_column(Float)
    avg_entry_price: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class OrderRecord(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    symbol: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)
    qty: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String)
    submitted_at: Mapped[datetime] = mapped_column(DateTime)
    filled_qty: Mapped[float] = mapped_column(Float, default=0.0)
    avg_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class EquitySnapshot(Base):
    """Append-only log -- never updated in place, so it doubles as the
    history a future dashboard (Stage 7) can chart directly."""

    __tablename__ = "equity_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)


class HeartbeatRecord(Base):
    """One row per monitored component, upserted in place (unlike
    EquitySnapshot, we only care about the *latest* beat, not history).
    This is a liveness signal, separate from trading activity -- a
    heartbeat should keep landing even on a day the strategy makes no
    trades (market closed, nothing eligible, etc.), so the dashboard can
    tell "engine alive, just idle" apart from "engine crashed"."""

    __tablename__ = "heartbeats"

    component: Mapped[str] = mapped_column(String, primary_key=True)
    last_beat_at: Mapped[datetime] = mapped_column(DateTime)
    detail: Mapped[str | None] = mapped_column(String, nullable=True)
