import pytest

from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    """Every test starts from a clean, .env-free environment so results
    don't depend on whatever is in the developer's real .env file."""
    env_keys = [
        "TRADING_MODE",
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "ALLOW_LEVERAGE",
        "MAX_LEVERAGE",
    ]
    for key in env_keys:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def make_settings():
    """Build a Settings object without touching a real .env file or env vars."""

    def _make(**overrides) -> Settings:
        return Settings(_env_file=None, **overrides)

    return _make
