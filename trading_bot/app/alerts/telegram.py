"""Telegram delivery for AlertEvents. Alerting must never be able to bring
down the process it's watching, so `send()` catches everything -- a bad
token, no network, Telegram being down, whatever -- and returns False
instead of raising. A missing bot_token/chat_id is treated as "alerts not
configured" and also just returns False, silently, so a bot can run in an
environment with no Telegram setup without that being an error.
"""
from __future__ import annotations

import logging
from typing import Protocol

from app.alerts.events import AlertEvent

logger = logging.getLogger("trading_bot.alerts.telegram")

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class HttpPoster(Protocol):
    """Just enough of `requests`' interface to be fakeable in tests."""

    def post(self, url: str, json: dict, timeout: float): ...


class _RequestsPoster:
    def post(self, url: str, json: dict, timeout: float):
        import requests

        return requests.post(url, json=json, timeout=timeout)


def format_message(event: AlertEvent) -> str:
    return f"[{event.severity.value}] {event.title}\n{event.detail}\n{event.timestamp.isoformat()}"


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, poster: HttpPoster | None = None, timeout: float = 10.0) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.poster = poster or _RequestsPoster()
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send(self, event: AlertEvent) -> bool:
        if not self.is_configured:
            return False

        url = _API_URL.format(token=self.bot_token)
        payload = {"chat_id": self.chat_id, "text": format_message(event)}
        try:
            response = self.poster.post(url, json=payload, timeout=self.timeout)
            if getattr(response, "status_code", None) == 200:
                return True
            logger.warning("Telegram send failed: status=%s", getattr(response, "status_code", "?"))
            return False
        except Exception as exc:
            # Never log str(exc) or use logger.exception() here: the request
            # URL embeds the bot token (https://api.telegram.org/bot<TOKEN>/...),
            # and network-layer exceptions (connection errors, timeouts) very
            # commonly include the offending URL in their own message. Logging
            # the exception body would leak the secret into the log file.
            logger.warning("Telegram send raised %s -- swallowed, alerting must never crash the caller", type(exc).__name__)
            return False
