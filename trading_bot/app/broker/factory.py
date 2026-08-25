"""Builds the real broker from Settings. Per the confirmed architecture,
PAPER and LIVE trading run through the identical AlpacaBroker class --
this function is the one place that decides which Alpaca endpoint that
instance talks to, driven entirely by `settings.trading_mode` via
`Settings.alpaca_base_url` (see app/config.py). APPROVAL mode uses the
paper endpoint, same as PAPER, since it has no live-money behavior yet.
"""
from __future__ import annotations

from app.broker.alpaca import AlpacaBroker
from app.config import Settings, TradingMode


def build_alpaca_broker(settings: Settings) -> AlpacaBroker:
    return AlpacaBroker(
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_secret_key,
        base_url=settings.alpaca_base_url,
        paper=settings.trading_mode != TradingMode.LIVE,
    )
