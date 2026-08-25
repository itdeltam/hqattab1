"""Manual, real-network sanity check for the Stage 9 Alpaca adapter.

Unlike every other demo script in this repo, this one is NOT run by the
test suite and NOT deterministic -- it makes real HTTP calls to Alpaca's
paper-trading endpoint using whatever ALPACA_API_KEY / ALPACA_SECRET_KEY
are configured in .env. It requires a real (free) Alpaca paper account.

Refuses to run at all if TRADING_MODE=LIVE, as a guard against this
manual script ever being pointed at a real-money account by accident --
this script exists to sanity-check the *paper* adapter, nothing more.

By default it only reads account/position state. Pass --submit-test-order
to also submit a 1-share market order (against your Alpaca *paper*
account -- fake money, but a real order Alpaca will record) and poll it
to a terminal state.

Run from trading_bot/:

    python scripts/run_alpaca_broker_demo.py
    python scripts/run_alpaca_broker_demo.py --submit-test-order [SYMBOL]
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.broker.factory import build_alpaca_broker
from app.broker.models import OrderRequest, OrderSide
from app.config import TradingMode, get_settings


def main() -> int:
    settings = get_settings()
    if settings.trading_mode == TradingMode.LIVE:
        print("Refusing to run: TRADING_MODE=LIVE. This script is for sanity-checking "
              "the paper adapter only. Set TRADING_MODE=PAPER in .env to run it.")
        return 1

    print(f"Connecting to {settings.alpaca_base_url} ...")
    broker = build_alpaca_broker(settings)

    account = broker.get_account()
    print(f"\nAccount: {account.account_id}")
    print(f"  Equity:       {account.equity:.2f}")
    print(f"  Cash:         {account.cash:.2f}")
    print(f"  Buying power: {account.buying_power:.2f}")

    positions = broker.get_positions()
    print(f"\nPositions ({len(positions)}):")
    for symbol, position in positions.items():
        print(f"  {symbol}: {position.qty} @ avg {position.avg_entry_price:.2f}")

    if "--submit-test-order" not in sys.argv:
        print("\n(Pass --submit-test-order [SYMBOL] to also submit and poll a 1-share "
              "market order against your Alpaca paper account.)")
        return 0

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    symbol = args[0] if args else "AAPL"

    print(f"\n--- Submitting a 1-share test BUY order for {symbol} (paper account) ---")
    now = datetime.now()
    order = broker.submit_order(OrderRequest(symbol=symbol, side=OrderSide.BUY, qty=1), now)
    print(f"Submitted: id={order.id} status={order.status.value}")
    if order.status.value == "rejected":
        print(f"Rejected: {order.rejection_reason}")
        return 1

    for _ in range(10):
        time.sleep(2)
        updated = broker.advance_time(datetime.now())
        current = broker.get_order(order.id)
        print(f"  status={current.status.value} filled={current.filled_qty}/{current.request.qty}")
        if not current.status.is_open:
            break

    return 0


if __name__ == "__main__":
    sys.exit(main())
