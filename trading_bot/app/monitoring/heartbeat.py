"""Liveness tracking, separate from trading activity. A heartbeat should
land on a fixed cadence (a future scheduler tick, e.g. every 60s) whether
or not the strategy actually traded that cycle -- that's what lets the
dashboard and HeartbeatMonitor tell "engine alive, just idle" apart from
"engine crashed or hung."
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.alerts.events import heartbeat_recovered, heartbeat_stale
from app.alerts.manager import AlertManager
from app.database.models import HeartbeatRecord

DEFAULT_HEARTBEAT_COMPONENT = "trading_engine"


def record_heartbeat(session: Session, component: str, now: datetime, detail: str | None = None) -> None:
    """Upsert -- only the latest beat matters, not a history of them."""
    existing = session.get(HeartbeatRecord, component)
    if existing is None:
        existing = HeartbeatRecord(component=component)
        session.add(existing)
    existing.last_beat_at = now
    existing.detail = detail
    session.commit()


def get_heartbeat(session: Session, component: str) -> HeartbeatRecord | None:
    return session.get(HeartbeatRecord, component)


def is_stale(last_beat_at: datetime | None, now: datetime, max_staleness_seconds: float) -> bool:
    if last_beat_at is None:
        return True
    return (now - last_beat_at).total_seconds() > max_staleness_seconds


class HeartbeatMonitor:
    """Wraps a component's heartbeat with edge-triggered alerting: fires a
    CRITICAL alert the moment a component goes stale, and an INFO alert the
    moment it recovers -- never repeats the same alert every single poll,
    which would just spam the channel into being ignored.
    """

    def __init__(
        self,
        session: Session,
        component: str,
        max_staleness_seconds: float,
        alert_manager: AlertManager,
    ) -> None:
        self.session = session
        self.component = component
        self.max_staleness_seconds = max_staleness_seconds
        self.alert_manager = alert_manager
        self._currently_stale: bool | None = None  # None = no verdict yet

    def check(self, now: datetime) -> bool:
        """Returns True if healthy. Fires an alert only on state transitions."""
        record = get_heartbeat(self.session, self.component)
        last_beat_at = record.last_beat_at if record else None
        stale = is_stale(last_beat_at, now, self.max_staleness_seconds)

        if stale and self._currently_stale is not True:
            self.alert_manager.notify(
                heartbeat_stale(self.component, last_beat_at, now, self.max_staleness_seconds)
            )
        elif not stale and self._currently_stale is True:
            self.alert_manager.notify(heartbeat_recovered(self.component, now))

        self._currently_stale = stale
        return not stale
