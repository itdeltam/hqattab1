"""app/bootstrap.py wires the real (non-test) TradingEngine and its
scheduler from Settings. These tests only inspect the wiring -- they
never call reconcile_on_startup() or build().start(), which would make
real network calls against whatever Alpaca credentials are configured.
Constructing AlpacaBroker/AlpacaMarketData/TradingClient themselves makes
no network call (confirmed: they just store config), so build_trading_scheduler()
is safe to call directly in a test as long as nothing downstream invokes it.
"""
from app.bootstrap import build_trading_scheduler
from app.broker.alpaca import AlpacaBroker
from app.market_data.alpaca_bars import AlpacaMarketData
from app.risk.engine import RiskEngine
from app.scheduling import TradingScheduler
from app.strategy.universe import DEFAULT_UNIVERSE


def test_build_trading_scheduler_wires_the_real_broker_and_market_data(make_settings):
    settings = make_settings(database_url="sqlite:///:memory:", alpaca_api_key="test-key", alpaca_secret_key="test-secret")

    scheduler = build_trading_scheduler(settings)

    assert isinstance(scheduler, TradingScheduler)
    assert isinstance(scheduler.engine.broker, AlpacaBroker)
    assert isinstance(scheduler.market_data, AlpacaMarketData)
    assert isinstance(scheduler.engine.risk_engine, RiskEngine)
    assert scheduler.universe == DEFAULT_UNIVERSE


def test_build_trading_scheduler_applies_scheduling_settings(make_settings):
    settings = make_settings(
        database_url="sqlite:///:memory:",
        alpaca_api_key="test-key", alpaca_secret_key="test-secret",
        heartbeat_interval_seconds=30,
        poll_fills_interval_seconds=45,
        rebalance_hour=10,
        rebalance_minute=15,
    )

    scheduler = build_trading_scheduler(settings)

    assert scheduler.heartbeat_interval_seconds == 30
    assert scheduler.poll_fills_interval_seconds == 45
    assert scheduler.rebalance_hour == 10
    assert scheduler.rebalance_minute == 15


def test_build_trading_scheduler_wires_the_price_cache_as_the_engines_price_lookup(make_settings):
    settings = make_settings(database_url="sqlite:///:memory:", alpaca_api_key="test-key", alpaca_secret_key="test-secret")

    scheduler = build_trading_scheduler(settings)
    scheduler.price_cache.update({"AAA": 123.45})

    assert scheduler.engine.price_lookup("AAA") == 123.45
