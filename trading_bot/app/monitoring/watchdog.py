"""In-process crash-restart supervisor. This is a second line of defense
underneath the OS-level one (NSSM, per the project's Windows deployment
plan) -- NSSM restarts the whole process if it dies outright; this catches
an unhandled exception from a single bad cycle inside a long-running loop
so a transient fault (one bad data point, one broker timeout) doesn't take
the whole process down and wait for an external supervisor to notice.

The property this module exists to guarantee: every single crash gets an
alert fired *before* any restart/backoff happens, and alerting itself can
never derail the restart loop (AlertManager already swallows sink
exceptions -- see app/alerts/manager.py -- so this module doesn't need to
guard against that itself, but the tests here verify the combination holds
end to end).
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Callable

from app.alerts.events import crash_detected, restart_limit_exceeded
from app.alerts.manager import AlertManager


def run_with_restart(
    target: Callable[[], None],
    component: str,
    alert_manager: AlertManager,
    max_restarts: int | None = None,
    initial_backoff_seconds: float = 1.0,
    max_backoff_seconds: float = 60.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    now_fn: Callable[[], datetime] = datetime.now,
) -> int:
    """Calls target() repeatedly, restarting it on any exception.

    A clean return from target() (no exception) ends the loop -- that's an
    intentional stop, not a crash, and is never alerted on. Returns the
    total number of restarts performed.

    Raises the triggering exception once max_restarts is exceeded, after
    firing a final alert -- at that point this is no longer this module's
    problem, and it's left to the OS-level supervisor (NSSM) to decide
    whether to restart the whole process.
    """
    restart_count = 0

    while True:
        try:
            target()
            return restart_count
        except Exception as exc:
            restart_count += 1
            alert_manager.notify(crash_detected(component, exc, restart_count, now_fn()))

            if max_restarts is not None and restart_count > max_restarts:
                alert_manager.notify(restart_limit_exceeded(component, restart_count, now_fn()))
                raise

            backoff = min(initial_backoff_seconds * (2 ** (restart_count - 1)), max_backoff_seconds)
            sleep_fn(backoff)
