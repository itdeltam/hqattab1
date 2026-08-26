"""AlpacaMarketData tests, all against a fake data client -- no real
network, no real credentials.
"""
import types
from datetime import datetime, timezone

import pandas as pd
import pytest

from app.market_data.alpaca_bars import AlpacaMarketData


def fake_bar(timestamp, close):
    return types.SimpleNamespace(timestamp=timestamp, close=close)


class FakeBarSet:
    def __init__(self, data: dict):
        self.data = data


class FakeDataClient:
    def __init__(self):
        self.bar_set = FakeBarSet({})
        self.latest_trades = {}
        self.bars_request = None
        self.trade_request = None

    def get_stock_bars(self, request_params):
        self.bars_request = request_params
        return self.bar_set

    def get_stock_latest_trade(self, request_params):
        self.trade_request = request_params
        return self.latest_trades


@pytest.fixture
def client():
    return FakeDataClient()


@pytest.fixture
def market_data(client):
    return AlpacaMarketData(api_key="k", secret_key="s", data_client=client)


def test_get_daily_close_history_builds_a_close_price_dataframe(market_data, client):
    client.bar_set = FakeBarSet({
        "AAA": [
            fake_bar(datetime(2024, 1, 2, tzinfo=timezone.utc), 100.0),
            fake_bar(datetime(2024, 1, 3, tzinfo=timezone.utc), 101.5),
        ],
        "BBB": [
            fake_bar(datetime(2024, 1, 2, tzinfo=timezone.utc), 50.0),
            fake_bar(datetime(2024, 1, 3, tzinfo=timezone.utc), 49.5),
        ],
    })

    df = market_data.get_daily_close_history(["AAA", "BBB"], datetime(2024, 1, 1), datetime(2024, 1, 3))

    assert list(df.columns) == ["AAA", "BBB"]
    assert df.loc[pd.Timestamp("2024-01-02"), "AAA"] == 100.0
    assert df.loc[pd.Timestamp("2024-01-03"), "BBB"] == 49.5


def test_get_daily_close_history_strips_timezone_and_normalizes_to_dates(market_data, client):
    """The index must be tz-naive, normalized dates -- consistent with
    every other price_history DataFrame in this codebase (e.g.
    app/backtesting/calendar.py's trading_sessions()) -- not a tz-aware
    intraday timestamp that would break .loc[latest] lookups elsewhere."""
    client.bar_set = FakeBarSet({
        "AAA": [fake_bar(datetime(2024, 1, 2, 5, 0, tzinfo=timezone.utc), 100.0)],
    })

    df = market_data.get_daily_close_history(["AAA"], datetime(2024, 1, 1), datetime(2024, 1, 3))

    assert df.index[0] == pd.Timestamp("2024-01-02")
    assert df.index.tz is None


def test_get_daily_close_history_omits_symbols_with_no_bars(market_data, client):
    client.bar_set = FakeBarSet({"AAA": [fake_bar(datetime(2024, 1, 2, tzinfo=timezone.utc), 100.0)]})
    # "BBB" requested but the broker returned nothing for it (e.g. newly listed, delisted, bad symbol)

    df = market_data.get_daily_close_history(["AAA", "BBB"], datetime(2024, 1, 1), datetime(2024, 1, 3))

    assert list(df.columns) == ["AAA"]


def test_get_daily_close_history_uses_split_and_dividend_adjusted_prices(market_data, client):
    from alpaca.data.enums import Adjustment

    market_data.get_daily_close_history(["AAA"], datetime(2024, 1, 1), datetime(2024, 1, 3))

    assert client.bars_request.adjustment == Adjustment.ALL


def test_get_latest_prices_returns_a_plain_symbol_to_price_dict(market_data, client):
    client.latest_trades = {
        "AAA": types.SimpleNamespace(price=101.25),
        "BBB": types.SimpleNamespace(price=49.75),
    }

    prices = market_data.get_latest_prices(["AAA", "BBB"])

    assert prices == {"AAA": 101.25, "BBB": 49.75}
