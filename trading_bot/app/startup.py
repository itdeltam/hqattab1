"""Startup-time safety gate.

This module owns the one rule that must never have an exception: the bot
may not place a real order in LIVE mode unless a human typed the exact
confirmation phrase at this process's startup, having been shown the
account, equity, and risk limits first. There is no config flag, env var,
or "skip confirmation" switch that bypasses this -- the only inputs are a
live TTY (or an injected callable in tests) and the phrase itself.
"""
from __future__ import annotations

from typing import Callable, Optional

from app.config import Settings, TradingMode

CONFIRMATION_PHRASE = "ENABLE LIVE TRADING"


class LiveTradingNotConfirmed(RuntimeError):
    """Raised when LIVE mode is requested but the typed confirmation was
    missing or incorrect. Startup must abort when this is raised."""


def _format_banner(settings: Settings, account_snapshot: Optional[dict]) -> str:
    account_snapshot = account_snapshot or {}
    limits = settings.risk_limits_summary()

    lines = [
        "=" * 60,
        "  LIVE TRADING MODE REQUESTED",
        "  Real money will be at risk. Review before proceeding.",
        "=" * 60,
        f"  Account ID     : {account_snapshot.get('account_id', 'UNKNOWN')}",
        f"  Equity         : {account_snapshot.get('equity', 'UNKNOWN')}",
        f"  Buying power   : {account_snapshot.get('buying_power', 'UNKNOWN')}",
        "-" * 60,
        f"  Starting capital     : {limits['starting_capital']}",
        f"  Max daily loss        : {limits['max_daily_loss_pct']:.2%}",
        f"  Max weekly loss       : {limits['max_weekly_loss_pct']:.2%}",
        f"  Max drawdown          : {limits['max_drawdown_pct']:.2%}",
        f"  Max position size     : {limits['max_position_pct']:.2%}",
        f"  Leverage allowed      : {limits['allow_leverage']} (max {limits['max_leverage']}x)",
        "=" * 60,
    ]
    return "\n".join(lines)


def enforce_mode_safety(
    settings: Settings,
    account_snapshot: Optional[dict] = None,
    confirm_input: Callable[[str], str] = input,
    printer: Callable[[str], None] = print,
) -> None:
    """Gate that must be called once at every process startup.

    - PAPER / APPROVAL: returns immediately, never prompts.
    - LIVE: prints the account/equity/risk-limit banner, then requires the
      operator to type CONFIRMATION_PHRASE exactly. Anything else raises
      LiveTradingNotConfirmed and the caller must not proceed to trading.
    """
    if settings.trading_mode != TradingMode.LIVE:
        return

    printer(_format_banner(settings, account_snapshot))
    try:
        response = confirm_input(
            f"Type '{CONFIRMATION_PHRASE}' to proceed, anything else aborts: "
        )
    except EOFError:
        # No interactive TTY available (e.g. started headless/as a service).
        # Fail safe: treat this exactly like a refused confirmation.
        response = ""

    # Strip a leading UTF-8 BOM: Windows/PowerShell prepends one when piping
    # text into a process's stdin, which would otherwise break an exact match.
    if response.strip().lstrip("﻿") != CONFIRMATION_PHRASE:
        raise LiveTradingNotConfirmed(
            "LIVE trading was not confirmed. Startup aborted; no trading will occur."
        )

    printer("LIVE trading confirmed by operator. Proceeding.")
