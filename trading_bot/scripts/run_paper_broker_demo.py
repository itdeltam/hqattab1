"""Manual sanity check for the Stage 5 paper broker: submits a market buy
that fills with latency and partial fills, then a sell, printing the order
lifecycle and account state at each step. Run from trading_bot/:

    python scripts/run_paper_broker_demo.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.backtesting.costs import FixedBpsSlippage
from app.broker.fills import PartialFillModel
from app.broker.latency import FixedLatency
from app.broker.models import OrderRequest, OrderSide
from app.broker.paper import PaperBroker


def main() -> None:
    prices = {"AAA": 100.0}
    now = datetime(2024, 1, 2, 9, 30)

    broker = PaperBroker(
        starting_cash=100_000.0,
        price_lookup=lambda s: prices.get(s),
        slippage_model=FixedBpsSlippage(bps=5),
        fill_quantity_model=PartialFillModel(fraction=0.5, min_remaining_qty=5),
        latency_model=FixedLatency(seconds=30),
    )

    print("--- Submitting buy order for 100 shares of AAA ---")
    order = broker.submit_order(OrderRequest("AAA", OrderSide.BUY, 100), now=now)
    print(f"Status right after submit: {order.status.value} (latency not yet elapsed)")

    for i in range(5):
        now += timedelta(seconds=30)
        broker.advance_time(now)
        current = broker.get_order(order.id)
        print(
            f"t+{30 * (i + 1)}s: status={current.status.value} "
            f"filled={current.filled_qty:.2f}/{current.request.qty} "
            f"avg_price={current.avg_fill_price}"
        )
        if current.status.value == "filled":
            break

    account = broker.get_account()
    print(f"\nAccount after buy: cash={account.cash:.2f} equity={account.equity:.2f}")

    prices["AAA"] = 110.0
    account = broker.get_account()
    print(f"Account after AAA moves to $110: equity={account.equity:.2f}")

    print("\n--- Submitting sell order for all 100 shares ---")
    sell_order = broker.submit_order(OrderRequest("AAA", OrderSide.SELL, 100), now=now)
    for i in range(5):
        now += timedelta(seconds=30)
        broker.advance_time(now)
        current = broker.get_order(sell_order.id)
        print(f"t+{30 * (i + 1)}s: status={current.status.value} filled={current.filled_qty:.2f}/100")
        if current.status.value == "filled":
            break

    account = broker.get_account()
    print(f"\nFinal account: cash={account.cash:.2f} equity={account.equity:.2f}")
    print(f"Positions: {broker.get_positions()}")


if __name__ == "__main__":
    main()
