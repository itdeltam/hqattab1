"""Fans an AlertEvent out to every configured sink. The one rule this
module exists to enforce: notify() can never raise, and one broken sink
(bad Telegram token, network down, a bug in a sink implementation) can
never stop the others -- or, more importantly, can never propagate back
into the trading/monitoring code that called notify() in the first place.
A failure in observability must stay strictly additive.
"""
from __future__ import annotations

import logging
from typing import Protocol

from app.alerts.events import AlertEvent

logger = logging.getLogger("trading_bot.alerts")

_LEVEL_BY_SEVERITY = {
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "CRITICAL": logging.CRITICAL,
}


class AlertSink(Protocol):
    def send(self, event: AlertEvent) -> bool: ...


class AlertManager:
    def __init__(self, sinks: list[AlertSink]) -> None:
        self.sinks = sinks

    def notify(self, event: AlertEvent) -> None:
        logger.log(_LEVEL_BY_SEVERITY.get(event.severity.value, logging.INFO), "%s: %s", event.title, event.detail)
        for sink in self.sinks:
            try:
                sink.send(event)
            except Exception:
                logger.exception("Alert sink %r raised -- swallowed, one broken sink must never stop the rest", sink)


def build_alert_manager(settings) -> AlertManager:
    from app.alerts.telegram import TelegramNotifier

    return AlertManager(sinks=[TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)])
