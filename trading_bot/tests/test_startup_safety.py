import pytest

from app.config import TradingMode
from app.startup import CONFIRMATION_PHRASE, LiveTradingNotConfirmed, enforce_mode_safety


def _silent_printer(_line: str) -> None:
    pass


@pytest.mark.parametrize("mode", [TradingMode.PAPER, TradingMode.APPROVAL])
def test_non_live_modes_never_prompt(make_settings, mode):
    settings = make_settings(trading_mode=mode)
    calls = []

    def confirm_input(_prompt: str) -> str:
        calls.append(_prompt)
        return CONFIRMATION_PHRASE  # would confirm if called; must NOT be called

    enforce_mode_safety(settings, confirm_input=confirm_input, printer=_silent_printer)
    assert calls == [], f"{mode} must never prompt for LIVE confirmation"


def test_live_mode_refused_with_no_input(make_settings):
    settings = make_settings(trading_mode=TradingMode.LIVE)

    def confirm_input(_prompt: str) -> str:
        return ""

    with pytest.raises(LiveTradingNotConfirmed):
        enforce_mode_safety(settings, confirm_input=confirm_input, printer=_silent_printer)


def test_live_mode_refused_with_wrong_phrase(make_settings):
    settings = make_settings(trading_mode=TradingMode.LIVE)

    def confirm_input(_prompt: str) -> str:
        return "yes enable it"

    with pytest.raises(LiveTradingNotConfirmed):
        enforce_mode_safety(settings, confirm_input=confirm_input, printer=_silent_printer)


def test_live_mode_refused_case_mismatch(make_settings):
    settings = make_settings(trading_mode=TradingMode.LIVE)

    def confirm_input(_prompt: str) -> str:
        return CONFIRMATION_PHRASE.lower()

    with pytest.raises(LiveTradingNotConfirmed):
        enforce_mode_safety(settings, confirm_input=confirm_input, printer=_silent_printer)


def test_live_mode_refused_on_eof_not_crash(make_settings):
    """Headless/service startup (no TTY, stdin closed) must refuse cleanly,
    not raise an uncaught EOFError."""
    settings = make_settings(trading_mode=TradingMode.LIVE)

    def confirm_input(_prompt: str) -> str:
        raise EOFError

    with pytest.raises(LiveTradingNotConfirmed):
        enforce_mode_safety(settings, confirm_input=confirm_input, printer=_silent_printer)


def test_live_mode_proceeds_with_leading_bom(make_settings):
    """Windows/PowerShell prepends a UTF-8 BOM when piping text into a
    process's stdin (e.g. `"phrase" | python -m app.main`). A correctly
    typed confirmation must still be accepted."""
    settings = make_settings(trading_mode=TradingMode.LIVE)

    def confirm_input(_prompt: str) -> str:
        return f"﻿{CONFIRMATION_PHRASE}"

    # Should not raise.
    enforce_mode_safety(settings, confirm_input=confirm_input, printer=_silent_printer)


def test_live_mode_proceeds_with_exact_phrase(make_settings):
    settings = make_settings(trading_mode=TradingMode.LIVE)

    def confirm_input(_prompt: str) -> str:
        return f"  {CONFIRMATION_PHRASE}  "  # incidental whitespace is fine

    # Should not raise.
    enforce_mode_safety(settings, confirm_input=confirm_input, printer=_silent_printer)


def test_live_mode_banner_shows_account_equity_and_risk_limits(make_settings):
    settings = make_settings(
        trading_mode=TradingMode.LIVE,
        starting_capital=50_000,
        max_drawdown_pct=0.12,
    )
    printed = []

    def confirm_input(_prompt: str) -> str:
        return CONFIRMATION_PHRASE

    enforce_mode_safety(
        settings,
        account_snapshot={"account_id": "ACC-123", "equity": "50000.00", "buying_power": "50000.00"},
        confirm_input=confirm_input,
        printer=printed.append,
    )

    banner = "\n".join(printed)
    assert "ACC-123" in banner
    assert "50000.00" in banner
    assert "12.00%" in banner  # max_drawdown_pct rendered as a percentage


def test_live_mode_confirmation_failure_raises_before_any_trading_flag():
    """Regression guard: the exception must be the only signal. There is no
    separate 'trading_enabled' state that could be left True by mistake."""
    from app.config import Settings

    settings = Settings(_env_file=None, trading_mode=TradingMode.LIVE)

    with pytest.raises(LiveTradingNotConfirmed):
        enforce_mode_safety(
            settings,
            confirm_input=lambda _p: "no",
            printer=_silent_printer,
        )
