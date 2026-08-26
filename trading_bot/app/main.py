"""Entrypoint. Wires config loading, the mode safety gate, and (Stage 11)
the full 24/7 scheduling loop. PAPER and LIVE both run through the same
`run()` path -- only the confirmation gate above it differs, per the
confirmed architecture."""
from __future__ import annotations

import logging
import sys
from datetime import datetime

from app.bootstrap import build_trading_scheduler
from app.broker.factory import build_alpaca_broker
from app.config import Settings, TradingMode, get_settings
from app.monitoring.watchdog import run_with_restart
from app.startup import LiveTradingNotConfirmed, enforce_mode_safety

logger = logging.getLogger("trading_bot")


def run(settings: Settings) -> int:
    """Builds the fully-wired engine, reconciles it against broker truth,
    then runs the scheduler forever. Blocks until interrupted (Ctrl+C,
    service stop) or the crash-restart watchdog exhausts its budget.

    Note: the watchdog here is a backstop against the *scheduler itself*
    failing, not against a job failing -- APScheduler swallows every
    exception a job raises internally and never re-raises it out of
    start(), so each job in app/scheduling.py alerts on its own failures
    directly. See that module's docstring.
    """
    trading_scheduler = build_trading_scheduler(settings)
    trading_scheduler.engine.reconcile_on_startup(datetime.now())

    scheduler = trading_scheduler.build()
    try:
        run_with_restart(scheduler.start, "trading_engine", trading_scheduler.engine.alert_manager)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown requested.")
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
    return 0


def main() -> int:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logger.info("Starting trading_bot in %s mode", settings.trading_mode.value)

    account_snapshot = None
    if settings.trading_mode == TradingMode.LIVE:
        # The confirmation banner must show real numbers, never
        # placeholders -- if we can't reach the broker to get them,
        # startup must abort before the banner is even shown, not proceed
        # with "UNKNOWN" and let the operator confirm blind.
        try:
            account = build_alpaca_broker(settings).get_account()
        except Exception:
            logger.exception(
                "Could not fetch account state from Alpaca. Refusing to start "
                "LIVE trading without real account/equity/risk numbers to show."
            )
            return 1
        account_snapshot = {
            "account_id": account.account_id or "UNKNOWN",
            "equity": account.equity,
            "buying_power": account.buying_power,
        }

    try:
        enforce_mode_safety(settings, account_snapshot=account_snapshot)
    except LiveTradingNotConfirmed as exc:
        logger.error("Refusing to start: %s", exc)
        return 1

    logger.info("Startup safety checks passed for %s mode. Starting the trading loop.", settings.trading_mode.value)
    return run(settings)


if __name__ == "__main__":
    sys.exit(main())
