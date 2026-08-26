"""TradingScheduler tests. Each job is called directly as a plain method
-- never through a running APScheduler instance -- per the module's own
design (see app/scheduling.py's docstring).

Flagship property: APScheduler's executor catches every exception a job
raises internally and never re-raises it to the caller of
scheduler.start() (verified against the installed apscheduler's own
run_job() source before writing this design) -- so each job method here
must catch its own failures and alert through the engine's AlertManager
directly. That's the real safety net for job failures, not the Stage 8
watchdog wrapped around scheduler.start() in app/main.py.
"""
from datetime import datetime

import pandas as pd
import pytest

from app.alerts.events import Severity
from app.alerts.manager import AlertManager
from app.market_data.live_price_cache import LivePriceCache
from app.scheduling import TradingScheduler

REBALANCE_DAY = datetime(2024, 1, 2, 9, 35)  # first NYSE session of Jan 2024
NON_REBALANCE_DAY = datetime(2024, 1, 3, 9, 35)


class RecordingSink:
    def __init__(self):
        self.events = []

    def send(self, event):
        self.events.append(event)
        return True


class FakeEngine:
    def __init__(self, alert_manager, raise_on=None):
        self.alert_manager = alert_manager
        self.raise_on = raise_on or set()
        self.heartbeat_calls = []
        self.poll_fills_calls = []
        self.rebalance_calls = []

    def heartbeat(self, now):
        if "heartbeat" in self.raise_on:
            raise RuntimeError("heartbeat broke")
        self.heartbeat_calls.append(now)

    def poll_fills(self, now):
        if "poll_fills" in self.raise_on:
            raise RuntimeError("poll_fills broke")
        self.poll_fills_calls.append(now)

    def run_rebalance_cycle(self, now, price_history, current_prices):
        if "rebalance" in self.raise_on:
            raise RuntimeError("rebalance broke")
        self.rebalance_calls.append((now, price_history, current_prices))
        return "CYCLE_RESULT"


class FakeMarketData:
    def __init__(self):
        self.history_calls = []
        self.latest_prices_calls = []
        self.history_result = pd.DataFrame({"AAA": [100.0, 101.0]})
        self.latest_prices_result = {"AAA": 101.5}

    def get_daily_close_history(self, symbols, start, end):
        self.history_calls.append((symbols, start, end))
        return self.history_result

    def get_latest_prices(self, symbols):
        self.latest_prices_calls.append(symbols)
        return self.latest_prices_result


@pytest.fixture
def sink():
    return RecordingSink()


@pytest.fixture
def alert_manager(sink):
    return AlertManager([sink])


@pytest.fixture
def market_data():
    return FakeMarketData()


@pytest.fixture
def price_cache():
    return LivePriceCache()


def make_scheduler(alert_manager, market_data, price_cache, raise_on=None):
    engine = FakeEngine(alert_manager, raise_on=raise_on)
    scheduler = TradingScheduler(
        engine=engine, market_data=market_data, price_cache=price_cache,
        universe=("AAA", "BBB"),
    )
    return scheduler, engine


def test_is_rebalance_day_true_on_first_session_of_month(alert_manager, market_data, price_cache):
    scheduler, _ = make_scheduler(alert_manager, market_data, price_cache)
    assert scheduler.is_rebalance_day(REBALANCE_DAY) is True


def test_is_rebalance_day_false_on_other_days(alert_manager, market_data, price_cache):
    scheduler, _ = make_scheduler(alert_manager, market_data, price_cache)
    assert scheduler.is_rebalance_day(NON_REBALANCE_DAY) is False


def test_run_heartbeat_calls_engine_heartbeat(alert_manager, market_data, price_cache):
    scheduler, engine = make_scheduler(alert_manager, market_data, price_cache)
    scheduler.run_heartbeat()
    assert len(engine.heartbeat_calls) == 1


def test_run_poll_fills_calls_engine_poll_fills(alert_manager, market_data, price_cache):
    scheduler, engine = make_scheduler(alert_manager, market_data, price_cache)
    scheduler.run_poll_fills()
    assert len(engine.poll_fills_calls) == 1


def test_run_rebalance_noops_on_a_non_rebalance_day(alert_manager, market_data, price_cache):
    scheduler, engine = make_scheduler(alert_manager, market_data, price_cache)

    result = scheduler.run_rebalance(NON_REBALANCE_DAY)

    assert result is None
    assert market_data.history_calls == []
    assert engine.rebalance_calls == []


def test_run_rebalance_fetches_data_and_runs_the_cycle_on_a_rebalance_day(alert_manager, market_data, price_cache):
    scheduler, engine = make_scheduler(alert_manager, market_data, price_cache)

    result = scheduler.run_rebalance(REBALANCE_DAY)

    assert result == "CYCLE_RESULT"
    assert len(market_data.history_calls) == 1
    assert market_data.history_calls[0][0] == ["AAA", "BBB"]
    assert len(engine.rebalance_calls) == 1


def test_run_rebalance_updates_the_price_cache_before_the_cycle(alert_manager, market_data, price_cache):
    scheduler, engine = make_scheduler(alert_manager, market_data, price_cache)

    scheduler.run_rebalance(REBALANCE_DAY)

    assert price_cache.get("AAA") == 101.5


@pytest.mark.parametrize("job_name,call_method", [
    ("heartbeat", lambda s: s.run_heartbeat()),
    ("poll_fills", lambda s: s.run_poll_fills()),
])
def test_heartbeat_and_poll_fills_job_failures_are_caught_and_alerted(job_name, call_method, alert_manager, market_data, price_cache, sink):
    scheduler, engine = make_scheduler(alert_manager, market_data, price_cache, raise_on={job_name})

    call_method(scheduler)  # must not raise

    assert len(sink.events) == 1
    assert sink.events[0].severity == Severity.CRITICAL
    assert job_name in sink.events[0].title


def test_rebalance_job_failure_is_caught_and_alerted_not_propagated(alert_manager, market_data, price_cache, sink):
    scheduler, engine = make_scheduler(alert_manager, market_data, price_cache, raise_on={"rebalance"})

    result = scheduler.run_rebalance(REBALANCE_DAY)  # must not raise

    assert result is None
    assert len(sink.events) == 1
    assert sink.events[0].severity == Severity.CRITICAL
    assert "rebalance" in sink.events[0].title


def test_build_registers_the_three_expected_jobs_without_starting(alert_manager, market_data, price_cache):
    scheduler, _ = make_scheduler(alert_manager, market_data, price_cache)

    apscheduler = scheduler.build()

    job_ids = {job.id for job in apscheduler.get_jobs()}
    assert job_ids == {"heartbeat", "poll_fills", "rebalance"}
    assert apscheduler.running is False  # build() must never call start()
