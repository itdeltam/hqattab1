"""In-process scheduling via APScheduler, per the confirmed architecture.
Three jobs on independent cadences:

- heartbeat: a fixed short interval, always running, independent of
  market hours -- see app/monitoring/heartbeat.py's "alive but idle" vs
  "crashed" distinction. It must keep landing on weekends/holidays too.
- poll_fills: a fixed short interval, resolves any pending broker orders.
- rebalance: fires every weekday at a fixed time, but only actually does
  anything on the strategy's real rebalance dates (the first NYSE session
  of each month, from app/backtesting/calendar.py) -- a no-op otherwise,
  so market holidays are excluded the same principled way the backtester
  excludes them, not by guessing at a cron expression that encodes them.

Each job is a plain, directly-callable method on TradingScheduler, not a
closure buried in scheduler wiring, so its logic is exercised in tests
without ever starting APScheduler's own thread/event loop.

Critical detail: APScheduler's executor catches *every* exception a job
raises internally (to keep its own loop alive) and never re-raises it to
the caller of scheduler.start() -- so wrapping start() in Stage 8's
crash-restart watchdog (see app/main.py) gives zero protection against a
job itself failing; a broken run_rebalance would otherwise fail silently
into APScheduler's own internal logger and nothing else. Each job method
here therefore catches its own exceptions and explicitly alerts through
the engine's AlertManager -- that is the real safety net for job
failures, not the watchdog around start().
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler

from app.alerts.events import AlertEvent, Severity
from app.backtesting.calendar import monthly_rebalance_dates, trading_sessions
from app.market_data.alpaca_bars import AlpacaMarketData
from app.market_data.live_price_cache import LivePriceCache
from app.trading_engine import CycleResult, TradingEngine

TIMEZONE = "America/New_York"
# Comfortably more than the longest signal lookback (252 sessions) in
# calendar days, so the fetched history is never short a trading day.
REBALANCE_LOOKBACK_DAYS = 400


@dataclass
class TradingScheduler:
    engine: TradingEngine
    market_data: AlpacaMarketData
    price_cache: LivePriceCache
    universe: tuple[str, ...]
    heartbeat_interval_seconds: int = 60
    poll_fills_interval_seconds: int = 60
    rebalance_hour: int = 9
    rebalance_minute: int = 35
    calendar: str = "NYSE"

    def _alert_job_failure(self, job_name: str, exc: Exception) -> None:
        self.engine.alert_manager.notify(AlertEvent(
            severity=Severity.CRITICAL,
            title=f"Scheduled job '{job_name}' failed",
            detail=f"{type(exc).__name__}: {exc}",
            timestamp=datetime.now(),
        ))

    def run_heartbeat(self, now: datetime | None = None) -> None:
        try:
            self.engine.heartbeat(now or datetime.now())
        except Exception as exc:
            self._alert_job_failure("heartbeat", exc)

    def run_poll_fills(self, now: datetime | None = None) -> None:
        try:
            self.engine.poll_fills(now or datetime.now())
        except Exception as exc:
            self._alert_job_failure("poll_fills", exc)

    def is_rebalance_day(self, now: datetime) -> bool:
        """True only on the first NYSE session of `now`'s calendar month.
        Fetches sessions from the 1st of the month (not just a short
        trailing window) so an early-month rebalance date is never missed
        out of the comparison set."""
        month_start = now.replace(day=1).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        sessions = trading_sessions(month_start, end, calendar=self.calendar)
        rebalance_dates = monthly_rebalance_dates(sessions)
        return now.date() in {d.date() for d in rebalance_dates}

    def run_rebalance(self, now: datetime | None = None) -> CycleResult | None:
        try:
            now = now or datetime.now()
            if not self.is_rebalance_day(now):
                return None

            symbols = list(self.universe)
            start = now - timedelta(days=REBALANCE_LOOKBACK_DAYS)
            price_history = self.market_data.get_daily_close_history(symbols, start, now)
            current_prices = self.market_data.get_latest_prices(symbols)
            self.price_cache.update(current_prices)

            return self.engine.run_rebalance_cycle(now, price_history, current_prices)
        except Exception as exc:
            self._alert_job_failure("rebalance", exc)
            return None

    def build(self) -> BlockingScheduler:
        scheduler = BlockingScheduler(timezone=TIMEZONE)
        scheduler.add_job(
            self.run_heartbeat, "interval", seconds=self.heartbeat_interval_seconds,
            id="heartbeat", max_instances=1,
        )
        scheduler.add_job(
            self.run_poll_fills, "interval", seconds=self.poll_fills_interval_seconds,
            id="poll_fills", max_instances=1,
        )
        scheduler.add_job(
            self.run_rebalance, "cron", day_of_week="mon-fri",
            hour=self.rebalance_hour, minute=self.rebalance_minute,
            id="rebalance", max_instances=1,
        )
        return scheduler
