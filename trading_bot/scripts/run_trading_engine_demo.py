"""Manual sanity check for the Stage 6 trading engine: reconciles a fresh
in-memory DB against a paper broker, runs one rebalance cycle against
synthetic data, polls for fills, and prints what happened at each step.
Run from trading_bot/:

    python scripts/run_trading_engine_demo.py
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.backtesting.costs import FixedBpsSlippage
from app.broker.paper import PaperBroker
from app.database.session import create_db_engine, make_session_factory
from app.market_data.synthetic import trending_series
from app.risk.engine import RiskEngine
from app.risk.limits import RiskLimits
from app.strategy.params import StrategyParams
from app.trading_engine import TradingEngine

SPECS = {
    "TECH_LIKE":   dict(annual_drift=0.18, annual_vol=0.20, seed=1),
    "UTIL_LIKE":   dict(annual_drift=0.05, annual_vol=0.10, seed=2),
    "ENERGY_LIKE": dict(annual_drift=-0.10, annual_vol=0.25, seed=3),
    "SHY":         dict(annual_drift=0.02, annual_vol=0.02, seed=4),
}


def main() -> None:
    dates = pd.bdate_range("2020-01-01", periods=400)
    price_history = pd.DataFrame({
        sym: trending_series(dates, p["annual_drift"], p["annual_vol"], seed=p["seed"])
        for sym, p in SPECS.items()
    })
    now = dates[-1].to_pydatetime() + timedelta(hours=9, minutes=30)
    current_prices = {sym: float(price_history.iloc[-1][sym]) for sym in price_history.columns}

    broker = PaperBroker(
        starting_cash=100_000.0,
        price_lookup=lambda s: current_prices.get(s),
        slippage_model=FixedBpsSlippage(bps=5),
    )
    engine_db = create_db_engine("sqlite:///:memory:")
    session = make_session_factory(engine_db)()

    params = StrategyParams(top_k=2, rank_buffer=1, defensive_asset="SHY")
    risk_engine = RiskEngine(RiskLimits(max_position_pct=0.60))
    trading_engine = TradingEngine(
        broker=broker, session=session, risk_engine=risk_engine,
        strategy_params=params, price_lookup=lambda s: current_prices.get(s),
    )

    print("--- Startup reconciliation ---")
    report = trading_engine.reconcile_on_startup(now)
    print(f"Clean: {report.is_clean}, discrepancies: {report.discrepancies}")

    print("\n--- Running rebalance cycle ---")
    result = trading_engine.run_rebalance_cycle(now, price_history, current_prices)
    print(f"Selected: {result.selected}")
    print(f"Target weights: {{ {', '.join(f'{k}: {v:.2%}' for k, v in result.target_weights.items())} }}")
    print(f"Proposed orders: {len(result.proposed_orders)}")
    for o in result.proposed_orders:
        print(f"  {o.side:4s} {o.shares:8.2f} {o.symbol}")
    print(f"Vetoed: {len(result.risk_decision.vetoed_orders)}")
    for v in result.risk_decision.vetoed_orders:
        print(f"  {v.order.symbol}: {v.reason}")
    if result.risk_decision.notes:
        print("Risk Engine notes:")
        for note in result.risk_decision.notes:
            print(f"  {note}")
    print(f"Submitted to broker: {len(result.submitted_orders)}")

    print("\n--- Polling for fills ---")
    filled = trading_engine.poll_fills(now)
    for o in filled:
        print(f"  {o.request.symbol}: {o.status.value}, {o.filled_qty:.2f} @ {o.avg_fill_price}")

    account = broker.get_account()
    print(f"\nFinal account: cash={account.cash:.2f} equity={account.equity:.2f}")
    print(f"Positions: {broker.get_positions()}")


if __name__ == "__main__":
    main()
