"""Entrypoint. Wires config loading and the mode safety gate. As of Stage
9 a real broker adapter exists, so a LIVE-mode startup can finally show
the operator real account numbers (not placeholders) before asking for
confirmation -- see the account_snapshot handling below. Full scheduler /
live-loop wiring (running rebalance cycles against real market data) is
deliberately deferred to Stage 11."""
from __future__ import annotations

import logging
import sys

from app.broker.factory import build_alpaca_broker
from app.config import TradingMode, get_settings
from app.startup import LiveTradingNotConfirmed, enforce_mode_safety

logger = logging.getLogger("trading_bot")


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

    logger.info(
        "Startup safety checks passed for %s mode. "
        "(Scheduler / live rebalance loop not yet wired: see Stage 11.)",
        settings.trading_mode.value,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
