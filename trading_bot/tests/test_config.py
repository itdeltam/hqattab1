import pytest
from pydantic import ValidationError

from app.config import Settings, TradingMode


def test_default_mode_is_paper(make_settings):
    settings = make_settings()
    assert settings.trading_mode == TradingMode.PAPER


def test_mode_reads_from_env(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "APPROVAL")
    settings = Settings(_env_file=None)
    assert settings.trading_mode == TradingMode.APPROVAL


def test_invalid_mode_rejected(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "YOLO")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_leverage_off_by_default(make_settings):
    settings = make_settings()
    assert settings.allow_leverage is False
    assert settings.max_leverage == 1.0


def test_leverage_above_1x_requires_explicit_opt_in(make_settings):
    with pytest.raises(ValidationError):
        make_settings(allow_leverage=False, max_leverage=2.0)


def test_leverage_above_1x_allowed_when_explicitly_enabled(make_settings):
    settings = make_settings(allow_leverage=True, max_leverage=2.0)
    assert settings.max_leverage == 2.0


def test_alpaca_base_url_is_paper_endpoint_unless_live(make_settings):
    paper = make_settings(trading_mode=TradingMode.PAPER)
    approval = make_settings(trading_mode=TradingMode.APPROVAL)
    live = make_settings(trading_mode=TradingMode.LIVE)

    assert paper.alpaca_base_url == paper.alpaca_paper_base_url
    assert approval.alpaca_base_url == approval.alpaca_paper_base_url
    assert live.alpaca_base_url == live.alpaca_live_base_url
    assert live.alpaca_base_url != live.alpaca_paper_base_url


def test_risk_limits_summary_contains_no_secrets(make_settings):
    settings = make_settings(
        alpaca_api_key="SECRET_KEY_ABC",
        alpaca_secret_key="SECRET_SECRET_XYZ",
    )
    summary_values = str(settings.risk_limits_summary())
    assert "SECRET_KEY_ABC" not in summary_values
    assert "SECRET_SECRET_XYZ" not in summary_values
