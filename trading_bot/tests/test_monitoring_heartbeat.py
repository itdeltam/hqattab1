"""Heartbeat is a liveness signal distinct from trading activity -- see the
module docstring in app/monitoring/heartbeat.py. These tests cover the
upsert semantics and, more importantly, HeartbeatMonitor's edge-triggered
alerting: it must fire exactly once on going stale and exactly once on
recovering, never repeat the same alert on every poll.
"""
from datetime import datetime, timedelta

from app.alerts.events import Severity
from app.alerts.manager import AlertManager
from app.database.session import create_db_engine, make_session_factory
from app.monitoring.heartbeat import HeartbeatMonitor, get_heartbeat, is_stale, record_heartbeat

NOW = datetime(2024, 1, 2, 9, 30)


class RecordingSink:
    def __init__(self):
        self.events = []

    def send(self, event):
        self.events.append(event)
        return True


def make_session():
    engine = create_db_engine("sqlite:///:memory:")
    factory = make_session_factory(engine)
    return factory()


def test_record_and_get_heartbeat_roundtrip():
    session = make_session()
    record_heartbeat(session, "trading_engine", NOW, detail="cycle ok")

    record = get_heartbeat(session, "trading_engine")

    assert record.last_beat_at == NOW
    assert record.detail == "cycle ok"


def test_record_heartbeat_upserts_not_duplicates():
    session = make_session()
    record_heartbeat(session, "trading_engine", NOW)
    record_heartbeat(session, "trading_engine", NOW + timedelta(minutes=1))

    record = get_heartbeat(session, "trading_engine")
    assert record.last_beat_at == NOW + timedelta(minutes=1)


def test_get_heartbeat_returns_none_when_never_recorded():
    session = make_session()
    assert get_heartbeat(session, "trading_engine") is None


def test_is_stale_none_is_always_stale():
    assert is_stale(None, NOW, max_staleness_seconds=120) is True


def test_is_stale_within_threshold_is_healthy():
    assert is_stale(NOW, NOW + timedelta(seconds=60), max_staleness_seconds=120) is False


def test_is_stale_past_threshold_is_stale():
    assert is_stale(NOW, NOW + timedelta(seconds=300), max_staleness_seconds=120) is True


def test_monitor_fires_critical_alert_once_on_first_stale_check():
    session = make_session()
    sink = RecordingSink()
    monitor = HeartbeatMonitor(session, "trading_engine", max_staleness_seconds=120, alert_manager=AlertManager([sink]))

    healthy = monitor.check(NOW)  # never beat -> stale from the start

    assert healthy is False
    assert len(sink.events) == 1
    assert sink.events[0].severity == Severity.CRITICAL


def test_monitor_does_not_repeat_the_alert_while_still_stale():
    session = make_session()
    sink = RecordingSink()
    monitor = HeartbeatMonitor(session, "trading_engine", max_staleness_seconds=120, alert_manager=AlertManager([sink]))

    monitor.check(NOW)
    monitor.check(NOW + timedelta(seconds=10))
    monitor.check(NOW + timedelta(seconds=20))

    assert len(sink.events) == 1  # edge-triggered, not once per poll


def test_monitor_fires_recovery_alert_on_transition_back_to_healthy():
    session = make_session()
    sink = RecordingSink()
    monitor = HeartbeatMonitor(session, "trading_engine", max_staleness_seconds=120, alert_manager=AlertManager([sink]))

    monitor.check(NOW)  # stale (never beat) -> 1 CRITICAL alert
    record_heartbeat(session, "trading_engine", NOW + timedelta(seconds=30))
    healthy = monitor.check(NOW + timedelta(seconds=31))

    assert healthy is True
    assert len(sink.events) == 2
    assert sink.events[1].severity == Severity.INFO


def test_monitor_stays_healthy_without_alerting_when_never_stale():
    session = make_session()
    sink = RecordingSink()
    record_heartbeat(session, "trading_engine", NOW)
    monitor = HeartbeatMonitor(session, "trading_engine", max_staleness_seconds=120, alert_manager=AlertManager([sink]))

    healthy = monitor.check(NOW + timedelta(seconds=10))

    assert healthy is True
    assert sink.events == []
