"""TelegramNotifier must never raise -- a bad token, no network, or
Telegram itself being down must degrade to "alert not delivered," never
to a crash of whatever called send().
"""
from datetime import datetime

from app.alerts.events import Severity, heartbeat_stale
from app.alerts.telegram import TelegramNotifier

NOW = datetime(2024, 1, 2, 9, 30)
EVENT = heartbeat_stale("trading_engine", None, NOW, 120)


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakePoster:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls = []

    def post(self, url, json, timeout):
        self.calls.append((url, json, timeout))
        if self.exc is not None:
            raise self.exc
        return self.response


def test_not_configured_returns_false_without_attempting_network_call():
    poster = FakePoster(response=FakeResponse(200))
    notifier = TelegramNotifier(bot_token="", chat_id="", poster=poster)

    assert notifier.send(EVENT) is False
    assert poster.calls == []


def test_successful_send_returns_true_and_posts_expected_payload():
    poster = FakePoster(response=FakeResponse(200))
    notifier = TelegramNotifier(bot_token="tok", chat_id="chat123", poster=poster)

    assert notifier.send(EVENT) is True
    url, payload, timeout = poster.calls[0]
    assert "tok" in url
    assert payload["chat_id"] == "chat123"
    assert "Heartbeat stale" in payload["text"]


def test_non_200_response_returns_false_without_raising():
    poster = FakePoster(response=FakeResponse(401))
    notifier = TelegramNotifier(bot_token="tok", chat_id="chat123", poster=poster)

    assert notifier.send(EVENT) is False


def test_network_exception_is_swallowed_and_returns_false():
    poster = FakePoster(exc=ConnectionError("no network"))
    notifier = TelegramNotifier(bot_token="tok", chat_id="chat123", poster=poster)

    assert notifier.send(EVENT) is False  # must not raise


def test_is_configured_reflects_token_and_chat_id_presence():
    assert TelegramNotifier("", "").is_configured is False
    assert TelegramNotifier("tok", "").is_configured is False
    assert TelegramNotifier("tok", "chat").is_configured is True
