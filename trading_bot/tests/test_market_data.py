import pandas as pd
import pytest

from app.market_data.bars import PriceHistory
from app.market_data.csv_loader import load_price_history_from_csv
from app.market_data.synthetic import generate_synthetic_history


def test_price_history_rejects_mismatched_index():
    dates_a = pd.bdate_range("2022-01-03", periods=5)
    dates_b = pd.bdate_range("2022-01-04", periods=5)
    close = pd.DataFrame({"A": range(5)}, index=dates_a)
    open_ = pd.DataFrame({"A": range(5)}, index=dates_b)

    with pytest.raises(ValueError, match="DatetimeIndex"):
        PriceHistory(close=close, open=open_)


def test_price_history_rejects_mismatched_columns():
    dates = pd.bdate_range("2022-01-03", periods=5)
    close = pd.DataFrame({"A": range(5)}, index=dates)
    open_ = pd.DataFrame({"B": range(5)}, index=dates)

    with pytest.raises(ValueError, match="symbol columns"):
        PriceHistory(close=close, open=open_)


def test_generate_synthetic_history_shape_and_open_lag():
    dates = pd.bdate_range("2022-01-03", periods=10)
    specs = {
        "A": {"annual_drift": 0.1, "annual_vol": 0.1, "seed": 1},
        "B": {"annual_drift": -0.1, "annual_vol": 0.2, "seed": 2},
    }
    history = generate_synthetic_history(specs, dates)

    assert history.symbols == ["A", "B"]
    assert len(history.dates) == 10
    # open[t] == close[t-1] for t > 0; open[0] == close[0] (no prior bar)
    assert (history.open.iloc[1:].values == history.close.iloc[:-1].values).all()
    assert (history.open.iloc[0] == history.close.iloc[0]).all()


def test_csv_loader_round_trip(tmp_path):
    df = pd.DataFrame({
        "date": pd.bdate_range("2022-01-03", periods=3),
        "open": [100.0, 101.0, 102.0],
        "close": [100.5, 101.5, 102.5],
    })
    df.to_csv(tmp_path / "AAA.csv", index=False)

    history = load_price_history_from_csv(tmp_path, ["AAA"])

    assert history.symbols == ["AAA"]
    assert history.close["AAA"].iloc[0] == 100.5
    assert history.open["AAA"].iloc[-1] == 102.0


def test_csv_loader_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_price_history_from_csv(tmp_path, ["NOPE"])


def test_csv_loader_missing_column_raises(tmp_path):
    df = pd.DataFrame({
        "date": pd.bdate_range("2022-01-03", periods=3),
        "close": [100.5, 101.5, 102.5],
    })
    df.to_csv(tmp_path / "BAD.csv", index=False)

    with pytest.raises(ValueError, match="missing required column"):
        load_price_history_from_csv(tmp_path, ["BAD"])
