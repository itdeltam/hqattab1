"""Central configuration for the trading bot.

Loads all settings from environment variables / a local .env file via
pydantic-settings. Nothing in this module ever hardcodes a secret, and
nothing in this module ever writes a secret to a log.
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(str, Enum):
    """The three (and only three) modes the bot can run in.

    PAPER    - default, simulated fills against Alpaca's paper endpoint.
    APPROVAL - simulated fills, reserved for a future human-approval gate.
    LIVE     - real money. Requires a typed confirmation at every startup
               (see app/startup.py). The bot never sets this mode itself.
    """

    PAPER = "PAPER"
    APPROVAL = "APPROVAL"
    LIVE = "LIVE"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Mode ---
    trading_mode: TradingMode = Field(default=TradingMode.PAPER)

    # --- Alpaca credentials (secrets: never logged, never printed) ---
    alpaca_api_key: str = Field(default="")
    alpaca_secret_key: str = Field(default="")
    alpaca_paper_base_url: str = Field(default="https://paper-api.alpaca.markets")
    alpaca_live_base_url: str = Field(default="https://api.alpaca.markets")

    # --- Telegram (secrets) ---
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")

    # --- Database ---
    database_url: str = Field(default="sqlite:///./data/trading_bot.db")

    # --- Capital & risk limits ---
    starting_capital: float = Field(default=100_000.0, gt=0)
    max_daily_loss_pct: float = Field(default=0.02, gt=0, le=1)
    max_weekly_loss_pct: float = Field(default=0.05, gt=0, le=1)
    max_drawdown_pct: float = Field(default=0.15, gt=0, le=1)
    max_position_pct: float = Field(default=0.10, gt=0, le=1)

    # --- Leverage: off unless explicitly turned on ---
    allow_leverage: bool = Field(default=False)
    max_leverage: float = Field(default=1.0, ge=1.0)

    # --- Monitoring ---
    heartbeat_stale_seconds: float = Field(default=120.0, gt=0)

    # --- Logging ---
    log_level: str = Field(default="INFO")

    @field_validator("max_leverage")
    @classmethod
    def _leverage_requires_explicit_opt_in(cls, v: float, info) -> float:
        allow = info.data.get("allow_leverage", False)
        if not allow and v > 1.0:
            raise ValueError(
                "max_leverage > 1.0 requires ALLOW_LEVERAGE=true to be set explicitly"
            )
        return v

    @property
    def alpaca_base_url(self) -> str:
        """The correct Alpaca endpoint for the current mode.

        LIVE is the only mode that talks to the real-money endpoint.
        """
        if self.trading_mode == TradingMode.LIVE:
            return self.alpaca_live_base_url
        return self.alpaca_paper_base_url

    def risk_limits_summary(self) -> dict:
        """Non-secret risk limits, safe to print/log/display on a dashboard."""
        return {
            "starting_capital": self.starting_capital,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_weekly_loss_pct": self.max_weekly_loss_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_position_pct": self.max_position_pct,
            "allow_leverage": self.allow_leverage,
            "max_leverage": self.max_leverage,
        }


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton. Use get_settings.cache_clear() in tests."""
    return Settings()
