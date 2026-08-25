"""Manual sanity check for the Stage 3 backtesting engine: runs it against
synthetic data (never real market data -- there's no market_data adapter
for that yet) and prints performance metrics. Run from trading_bot/:

    python scripts/run_backtest_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.backtesting.calendar import monthly_rebalance_dates, trading_sessions
from app.backtesting.engine import BacktestConfig, BacktestEngine
from app.backtesting.metrics import annualized_vol, cagr, max_drawdown, sharpe_ratio, total_return
from app.market_data.bars import PriceHistory
from app.market_data.synthetic import trending_series
from app.strategy.params import StrategyParams

SPECS = {
    "TECH_LIKE":   dict(annual_drift=0.15, annual_vol=0.22, seed=1),
    "UTIL_LIKE":   dict(annual_drift=0.06, annual_vol=0.12, seed=2),
    "ENERGY_LIKE": dict(annual_drift=-0.05, annual_vol=0.28, seed=3),
    "BONDS_LIKE":  dict(annual_drift=0.03, annual_vol=0.08, seed=4),
    "SHY":         dict(annual_drift=0.02, annual_vol=0.02, seed=5),
}


def main() -> None:
    sessions = trading_sessions("2015-01-01", "2023-12-31")
    close = pd.DataFrame({
        sym: trending_series(sessions, p["annual_drift"], p["annual_vol"], seed=p["seed"])
        for sym, p in SPECS.items()
    })
    open_ = close.shift(1)
    open_.iloc[0] = close.iloc[0]
    history = PriceHistory(close=close, open=open_)

    rebalances = monthly_rebalance_dates(sessions)
    params = StrategyParams(top_k=3, rank_buffer=1, defensive_asset="SHY")
    config = BacktestConfig(starting_capital=100_000.0, strategy_params=params)

    result = BacktestEngine(config).run(history, rebalances)

    print(f"Period: {sessions[0].date()} to {sessions[-1].date()} ({len(sessions)} sessions)")
    print(f"Starting capital : {config.starting_capital:,.2f}")
    print(f"Ending equity    : {result.equity_curve.iloc[-1]:,.2f}")
    print(f"Total return     : {total_return(result.equity_curve):.2%}")
    print(f"CAGR             : {cagr(result.equity_curve):.2%}")
    print(f"Max drawdown     : {max_drawdown(result.equity_curve):.2%}")
    print(f"Annualized vol   : {annualized_vol(result.equity_curve):.2%}")
    print(f"Sharpe ratio     : {sharpe_ratio(result.equity_curve):.2f}")
    print(f"Total trades     : {len(result.trades)}")


if __name__ == "__main__":
    main()
