"""Alert event shapes. Kept as plain data + small factory functions --
callers build an AlertEvent and hand it to an AlertManager; nothing here
knows how an event gets delivered (Telegram, log, or otherwise).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class AlertEvent:
    severity: Severity
    title: str
    detail: str
    timestamp: datetime


def engine_started(mode: str, now: datetime) -> AlertEvent:
    return AlertEvent(Severity.INFO, "Trading bot started", f"Mode: {mode}", now)


def heartbeat_stale(component: str, last_beat_at: datetime | None, now: datetime, max_staleness_seconds: float) -> AlertEvent:
    if last_beat_at is None:
        detail = f"No heartbeat has ever been recorded for '{component}'."
    else:
        age = (now - last_beat_at).total_seconds()
        detail = (
            f"'{component}' has not reported in {age:.0f}s "
            f"(threshold: {max_staleness_seconds:.0f}s). Last beat: {last_beat_at}."
        )
    return AlertEvent(Severity.CRITICAL, f"Heartbeat stale: {component}", detail, now)


def heartbeat_recovered(component: str, now: datetime) -> AlertEvent:
    return AlertEvent(Severity.INFO, f"Heartbeat recovered: {component}", f"'{component}' is reporting again.", now)


def crash_detected(component: str, exc: BaseException, restart_count: int, now: datetime) -> AlertEvent:
    detail = f"Restart #{restart_count}. {type(exc).__name__}: {exc}"
    return AlertEvent(Severity.CRITICAL, f"Crash in {component}", detail, now)


def restart_limit_exceeded(component: str, restart_count: int, now: datetime) -> AlertEvent:
    detail = f"'{component}' crashed {restart_count} times and hit its restart limit. Giving up -- it will not restart again on its own."
    return AlertEvent(Severity.CRITICAL, f"Restart limit exceeded: {component}", detail, now)
