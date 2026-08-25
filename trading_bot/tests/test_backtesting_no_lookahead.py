import pandas as pd

from app.backtesting.calendar import monthly_rebalance_dates, trading_sessions
from app.backtesting.engine import BacktestConfig, BacktestEngine
from app.market_data.bars import PriceHistory
from app.market_data.synthetic import trending_series
from app.strategy.params import StrategyParams

SPECS = {
    "A": dict(annual_drift=0.15, annual_vol=0.12, seed=1),
    "B": dict(annual_drift=-0.05, annual_vol=0.20, seed=2),
    "SHY": dict(annual_drift=0.02, annual_vol=0.02, seed=3),
}


def _to_history(close: pd.DataFrame) -> PriceHistory:
    open_ = close.shift(1)
    open_.iloc[0] = close.iloc[0]
    return PriceHistory(close=close, open=open_)


def test_no_lookahead_future_prices_never_affect_past_decisions():
    """The strongest form of this check: two histories identical up to a
    split date, then diverging wildly (a synthetic crash injected only in
    the future segment). If anything in the engine ever reads a future
    value to make a past decision, the pre-split results would differ
    between the two runs. They must not."""
    sessions = trading_sessions("2019-01-01", "2021-12-31")
    split_date = sessions[len(sessions) * 2 // 3]

    close_baseline = pd.DataFrame({
        sym: trending_series(sessions, p["annual_drift"], p["annual_vol"], seed=p["seed"])
        for sym, p in SPECS.items()
    })

    close_altered_future = close_baseline.copy()
    future_mask = close_altered_future.index > split_date
    close_altered_future.loc[future_mask] = close_altered_future.loc[future_mask] * 0.1

    history_baseline = _to_history(close_baseline)
    history_altered = _to_history(close_altered_future)

    rebalances = monthly_rebalance_dates(sessions)
    config = BacktestConfig(strategy_params=StrategyParams(defensive_asset="SHY"))

    result_baseline = BacktestEngine(config).run(history_baseline, rebalances)
    result_altered = BacktestEngine(config).run(history_altered, rebalances)

    pd.testing.assert_series_equal(
        result_baseline.equity_curve.loc[:split_date],
        result_altered.equity_curve.loc[:split_date],
    )

    trades_baseline_past = [t for t in result_baseline.trades if t.date <= split_date]
    trades_altered_past = [t for t in result_altered.trades if t.date <= split_date]
    assert trades_baseline_past == trades_altered_past

    # Sanity check the test itself isn't vacuous -- the crash must actually
    # have changed something after the split.
    assert not result_baseline.equity_curve.loc[split_date:].equals(
        result_altered.equity_curve.loc[split_date:]
    )
