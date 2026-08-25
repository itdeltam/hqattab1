"""Entrypoint. Stage 1 only wires config loading and the mode safety gate;
market data, strategy, risk, and execution are added in later stages."""
from __future__ import annotations

import logging
import sys

from app.config import get_settings
from app.startup import LiveTradingNotConfirmed, enforce_mode_safety

logger = logging.getLogger("trading_bot")


def main() -> int:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logger.info("Starting trading_bot in %s mode", settings.trading_mode.value)

    try:
        # account_snapshot is None until the broker adapter exists (Stage 9).
        enforce_mode_safety(settings, account_snapshot=None)
    except LiveTradingNotConfirmed as exc:
        logger.error("Refusing to start: %s", exc)
        return 1

    logger.info(
        "Startup safety checks passed for %s mode. "
        "(Stages 2-9 not yet wired: no strategy/risk/execution loop runs yet.)",
        settings.trading_mode.value,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
