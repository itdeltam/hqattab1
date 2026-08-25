# trading_bot

A 24/7 autonomous algorithmic trading system for US equities/ETFs (long-only,
diversified trend/momentum), built on Alpaca, SQLite/SQLAlchemy, and FastAPI.

Built stage by stage; see `BUILD ORDER` in the project brief. **Stages 1-3
(scaffolding/config, strategy math spec, backtesting engine) are done.**
Stages 4-12 are not implemented yet.

## Safety model (non-negotiable, see project brief for full list)

- Three modes: `PAPER` (default), `APPROVAL`, `LIVE`. The app never
  auto-switches itself into LIVE.
- Starting the app in `LIVE` mode requires typing `ENABLE LIVE TRADING`
  exactly, after being shown account, equity, and risk limits. See
  `app/startup.py`.
- No secrets are hardcoded or logged. All credentials come from `.env`
  (see `.env.example`), which is git-ignored.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env       # then fill in real values
```

**Before any real trading**, edit `.env` and set real numbers for
`STARTING_CAPITAL` and `MAX_DRAWDOWN_PCT` (and the other risk limits) — the
defaults in `.env.example` are placeholders, not recommendations.

## Run

```powershell
python -m app.main
```

In `PAPER` or `APPROVAL` mode this starts immediately. In `LIVE` mode it
will print an account/risk-limit banner and block on a typed confirmation.

On Windows, `start_trader.bat` wraps this for use with NSSM (auto-start /
auto-restart) — see the comment header in that file.

## Test

```powershell
pytest
```

`tests/test_startup_safety.py` is the load-bearing test suite for Stage 1:
it asserts PAPER/APPROVAL never prompt, and LIVE mode refuses to proceed
without the exact typed confirmation phrase.

`tests/test_backtesting_no_lookahead.py` is the load-bearing test for
Stage 3: two price histories identical up to a split date, then diverging
wildly after it (a synthetic crash injected only in the future segment) —
the backtest's pre-split trades and equity curve must be byte-identical
between the two runs, proving nothing in the engine reads ahead.

Run a demo backtest against synthetic data and print performance metrics:

```powershell
python scripts\run_backtest_demo.py
```

## Research

`research/stage2_strategy_math_spec.ipynb` is the Stage 2 deliverable: the
trend/momentum signal math (trend filter, vol-adjusted momentum score,
selection with a turnover buffer, inverse-vol position sizing), justified,
and validated against synthetic data. `app/strategy/` is that same math
ported into production code once Stage 3's backtester existed to validate
it. `research/_build_notebook.py` regenerates the notebook if it needs
edits (`python _build_notebook.py`, then
`jupyter nbconvert --to notebook --execute --inplace stage2_strategy_math_spec.ipynb`).

## Backtesting (Stage 3)

`app/backtesting/` walks real NYSE trading sessions (`pandas_market_calendars`,
never naive calendar-day math) one at a time. On each monthly rebalance
date it computes signals using data through the *prior* session's close
only, then executes at the rebalance date's *open* with configurable
commission (`app/backtesting/costs.py`, defaults to Alpaca's real $0
equities/ETF commission) and slippage (fixed bps against the trader by
default). `app/market_data/` currently has a synthetic generator (tests
and the demo script) and a CSV loader; a real historical-data adapter is
Stage 9 scope, not Stage 3.

No real market data is used yet anywhere in this repo -- everything above
runs on synthetic data with known, designed-in properties.
