"""Flagship test for Stage 8. The non-negotiable property here: a failure
anywhere in the monitoring/alerting layer must be strictly additive -- it
can never propagate back into the trading loop it's supposed to be
watching. That means AlertManager.notify() must never raise even when
every sink raises, and the crash-restart watchdog must keep restarting
even when the act of *alerting about* a crash itself blows up.

This mirrors the pattern established by every other stage's flagship test
(e.g. test_risk_engine_never_overridden.py): don't just document the
rule, make it mechanically checkable.
"""
from datetime import datetime

import pytest

from app.alerts.events import Severity, crash_detected
from app.alerts.manager import AlertManager
from app.monitoring.watchdog import run_with_restart

NOW = datetime(2024, 1, 2, 9, 30)


class ExplodingSink:
    """Simulates a totally broken alert channel -- bad token, DNS failure,
    a bug in a third-party client, anything."""

    def send(self, event):
        raise RuntimeError("this sink is completely broken")


class RecordingSink:
    def __init__(self):
        self.events = []

    def send(self, event):
        self.events.append(event)
        return True


@pytest.mark.parametrize("severity_event", [
    crash_detected("comp", ValueError("x"), 1, NOW),
])
def test_alert_manager_swallows_every_sink_exception(severity_event):
    good_sink = RecordingSink()
    manager = AlertManager(sinks=[ExplodingSink(), good_sink, ExplodingSink()])

    manager.notify(severity_event)  # must not raise

    assert good_sink.events == [severity_event]  # sinks around the broken ones still ran


def test_alert_manager_notify_never_raises_even_when_every_sink_is_broken():
    manager = AlertManager(sinks=[ExplodingSink(), ExplodingSink()])

    manager.notify(crash_detected("comp", ValueError("x"), 1, NOW))  # must not raise


def test_watchdog_keeps_restarting_even_when_alerting_about_the_crash_itself_fails():
    manager = AlertManager(sinks=[ExplodingSink()])
    attempts = {"count": 0}

    def flaky_target():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError(f"boom #{attempts['count']}")
        return  # succeeds on the 3rd attempt -> clean stop

    restarts = run_with_restart(
        flaky_target, "trading_engine", manager,
        max_restarts=5, sleep_fn=lambda seconds: None,
    )

    assert attempts["count"] == 3
    assert restarts == 2  # 2 crashes before the clean run


def test_watchdog_raises_and_alerts_once_max_restarts_is_exceeded():
    sink = RecordingSink()
    manager = AlertManager(sinks=[sink])

    def always_fails():
        raise RuntimeError("permanently broken")

    with pytest.raises(RuntimeError):
        run_with_restart(always_fails, "trading_engine", manager, max_restarts=2, sleep_fn=lambda s: None)

    # 3 crash alerts (attempts 1,2,3) + 1 final "restart limit exceeded" alert
    assert len(sink.events) == 4
    assert sink.events[-1].severity == Severity.CRITICAL
    assert "limit" in sink.events[-1].title.lower()


def test_watchdog_backoff_grows_and_caps():
    manager = AlertManager(sinks=[])
    sleeps = []
    attempts = {"count": 0}

    def flaky_target():
        attempts["count"] += 1
        if attempts["count"] <= 4:
            raise RuntimeError("boom")

    run_with_restart(
        flaky_target, "trading_engine", manager,
        max_restarts=10, initial_backoff_seconds=1.0, max_backoff_seconds=5.0,
        sleep_fn=sleeps.append,
    )

    assert sleeps == [1.0, 2.0, 4.0, 5.0]  # doubles each time, capped at 5.0


def test_clean_return_never_restarts_and_never_alerts():
    sink = RecordingSink()
    manager = AlertManager(sinks=[sink])

    restarts = run_with_restart(lambda: None, "trading_engine", manager, sleep_fn=lambda s: None)

    assert restarts == 0
    assert sink.events == []


def test_alert_fires_before_backoff_sleep_on_every_single_crash():
    """Ordering matters: an operator must be alerted before the process
    goes quiet to sleep off a backoff, not after."""
    manager = AlertManager(sinks=[])
    order = []
    real_notify = manager.notify

    def spying_notify(event):
        order.append(("alert", event.title))
        real_notify(event)

    manager.notify = spying_notify

    attempts = {"count": 0}

    def flaky_target():
        attempts["count"] += 1
        if attempts["count"] <= 2:
            raise RuntimeError("boom")

    run_with_restart(
        flaky_target, "trading_engine", manager, max_restarts=5,
        sleep_fn=lambda seconds: order.append(("sleep", seconds)),
    )

    assert order[0][0] == "alert"
    assert order[1][0] == "sleep"
    assert order[2][0] == "alert"
    assert order[3][0] == "sleep"
