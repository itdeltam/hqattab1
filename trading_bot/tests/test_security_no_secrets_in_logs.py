"""Stage 10 security testing. Flagship finding: the Telegram bot token is
embedded directly in the request URL
(https://api.telegram.org/bot<TOKEN>/sendMessage), and network-layer
exceptions (connection errors, timeouts) very commonly include the
offending URL in their own message. Logging that exception's message or
traceback -- which app/alerts/telegram.py used to do via
logger.exception(...) -- would leak the secret straight into the log
file, in direct violation of the project's non-negotiable "never log API
keys/secrets" rule. This suite proves it can't happen, across every
failure path that touches the logger.
"""
import logging

import pytest

from app.alerts.events import heartbeat_stale
from app.alerts.telegram import TelegramNotifier
from datetime import datetime

NOW = datetime(2024, 1, 2, 9, 30)
SECRET_TOKEN = "123456:AA-super-secret-telegram-token-do-not-leak"
EVENT = heartbeat_stale("trading_engine", None, NOW, 120)


class TokenLeakingPoster:
    """Simulates what real network exceptions actually do: embed the
    request URL (and therefore the token) in their own message."""

    def __init__(self, exc_factory):
        self._exc_factory = exc_factory

    def post(self, url, json, timeout):
        raise self._exc_factory(url)


@pytest.mark.parametrize("exc_factory", [
    lambda url: ConnectionError(f"Failed to establish a new connection: {url}"),
    lambda url: TimeoutError(f"Request timed out: {url}"),
    lambda url: RuntimeError(f"HTTPSConnectionPool(host='api.telegram.org'): Max retries exceeded with url: {url}"),
])
def test_telegram_failure_never_logs_the_bot_token(caplog, exc_factory):
    poster = TokenLeakingPoster(exc_factory)
    notifier = TelegramNotifier(bot_token=SECRET_TOKEN, chat_id="chat123", poster=poster)

    with caplog.at_level(logging.DEBUG):
        result = notifier.send(EVENT)

    assert result is False
    all_logged_text = "\n".join(record.getMessage() for record in caplog.records)
    assert SECRET_TOKEN not in all_logged_text
    # Also check the fully-formatted record (includes exc_info text, if any).
    for record in caplog.records:
        formatted = logging.Formatter().format(record)
        assert SECRET_TOKEN not in formatted


def test_telegram_failure_does_not_use_exc_info_traceback(caplog):
    """logger.exception()/exc_info=True would render the exception's own
    __str__ (which may contain the token-bearing URL) into the log
    record. Assert no record carries exception info at all."""
    poster = TokenLeakingPoster(lambda url: ConnectionError(url))
    notifier = TelegramNotifier(bot_token=SECRET_TOKEN, chat_id="chat123", poster=poster)

    with caplog.at_level(logging.DEBUG):
        notifier.send(EVENT)

    assert all(record.exc_info is None for record in caplog.records)


def test_not_configured_notifier_never_logs_anything_containing_a_token(caplog):
    # bot_token empty here, but prove the *general* invariant: whatever a
    # deployment's real token would be, is_configured=False must short
    # circuit before any URL is even built.
    notifier = TelegramNotifier(bot_token="", chat_id="")

    with caplog.at_level(logging.DEBUG):
        result = notifier.send(EVENT)

    assert result is False
    assert caplog.records == []
