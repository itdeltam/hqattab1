"""Assembles the real (non-test) TradingEngine and its scheduler from
Settings -- the one place that wires together the broker, market data,
risk limits, alerts, and database session for an actual deployment.

Kept separate from app/main.py so this construction can be exercised and
inspected in tests without ever calling the blocking
TradingScheduler.build().start().
"""
from __future__ import annotations

from app.alerts.manager import build_alert_manager
from app.broker.factory import build_alpaca_broker
from app.config import Settings
from app.database.session import create_db_engine, make_session_factory
from app.market_data.alpaca_bars import AlpacaMarketData
from app.market_data.live_price_cache import LivePriceCache
from app.risk.config import load_risk_limits
from app.risk.engine import RiskEngine
from app.scheduling import TradingScheduler
from app.strategy.params import StrategyParams
from app.strategy.universe import DEFAULT_UNIVERSE
from app.trading_engine import TradingEngine


def build_trading_scheduler(settings: Settings) -> TradingScheduler:
    db_engine = create_db_engine(settings.database_url)
    session = make_session_factory(db_engine)()

    broker = build_alpaca_broker(settings)
    market_data = AlpacaMarketData(settings.alpaca_api_key, settings.alpaca_secret_key)
    price_cache = LivePriceCache()

    engine = TradingEngine(
        broker=broker,
        session=session,
        risk_engine=RiskEngine(load_risk_limits(settings)),
        strategy_params=StrategyParams(),
        price_lookup=price_cache.get,
        alert_manager=build_alert_manager(settings),
    )

    return TradingScheduler(
        engine=engine,
        market_data=market_data,
        price_cache=price_cache,
        universe=DEFAULT_UNIVERSE,
        heartbeat_interval_seconds=settings.heartbeat_interval_seconds,
        poll_fills_interval_seconds=settings.poll_fills_interval_seconds,
        rebalance_hour=settings.rebalance_hour,
        rebalance_minute=settings.rebalance_minute,
    )
