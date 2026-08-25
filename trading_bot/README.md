# trading_bot

A 24/7 autonomous algorithmic trading system for US equities/ETFs (long-only,
diversified trend/momentum), built on Alpaca, SQLite/SQLAlchemy, and FastAPI.

Built stage by stage; see `BUILD ORDER` in the project brief. **Stages 1-5
(scaffolding/config, strategy math spec, backtesting engine, risk engine,
paper broker simulator) are done.** Stages 6-12 are not implemented yet.

## Safety model (non-negotiable, see project brief for full list)

- Three modes: `PAPER` (default), `APPROVAL`, `LIVE`. The app never
  auto-switches itself into LIVE.
- Starting the app in `LIVE` mode requires typing `ENABLE LIVE TRADING`
  exactly, after being shown account, equity, and risk limits. See
  `app/startup.py`.
- No secrets are hardcoded or logged. All credentials come from `.env`
  (see `.env.example`), which is git-ignored.
- The Risk Engine (`app/risk/`) can veto or clip any trade the Strategy
  proposes. No config flag, order metadata, or "confidence" field can
  override it — see `tests/test_risk_engine_never_overridden.py`.
- No martingale/doubling down: refusing to add to a position already
  underwater past a configured threshold. No leverage unless
  `ALLOW_LEVERAGE=true` is set explicitly, and even then capped at
  `MAX_LEVERAGE`. Never shorts (long-only, no exceptions).

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

`tests/test_broker_latency.py` and `tests/test_broker_partial_fills.py`
are the load-bearing tests for Stage 5: latency delays fills until the
scheduled time (never early, using the price *at fill time* not submit
time), and partial fills accumulate correctly toward the original order
quantity with a properly weighted average fill price.

Run a demo backtest against synthetic data and print performance metrics:

```powershell
python scripts\run_backtest_demo.py
```

Run a demo paper-broker order lifecycle (submit, partial fills over time,
latency, sell, final account state):

```powershell
python scripts\run_paper_broker_demo.py
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

## Risk Engine (Stage 4)

`app/risk/` is a separate, dependency-free module (no imports of
app.config, app.strategy, or anything else in the app) so it can be
unit-tested in complete isolation, per the project's build order. It is
the mandatory gate every proposed order passes through:

- **Position limits** — clips a buy that would push a symbol over
  `MAX_POSITION_PCT` of equity; fully vetoes if already at/above the cap.
- **No leverage unless enabled** — gross exposure capped at 100% of equity
  unless `ALLOW_LEVERAGE=true`, in which case it's still capped at
  `MAX_LEVERAGE`.
- **Never shorts** — a sell can never exceed shares actually held.
- **No martingale/doubling down** — refuses to add to a position already
  underwater past `max_add_to_loser_pct` (`config/risk_limits.yaml`).
  Never blocks opening a brand-new position.
- **Daily/weekly loss limits and a drawdown kill switch** — once
  breached, all new risk-increasing (buy) orders are blocked; sells
  (risk-reducing) are always still allowed through.
- **Correlation limits** — two positions correlated at or above
  `max_correlation` can't jointly exceed `max_correlated_group_pct` of
  equity (pairwise check, `config/risk_limits.yaml`).

`RiskLimits` is built from two sources: the existing `.env`/`Settings`
fields (position/loss/drawdown/leverage, established in Stage 1) merged
with `config/risk_limits.yaml` (the new Stage 4 knobs: correlation and
anti-martingale) via `app/risk/config.py`.

`tests/test_risk_engine_never_overridden.py` is the load-bearing test for
this stage: every veto/clip rule above is tested twice per scenario, once
with a plain order and once with an order whose metadata claims maximal
strategy confidence (including an explicit `override_requested: True`
flag) — both must produce the identical outcome. This mechanically proves
the "no exceptions, no overrides" rule rather than just asserting it in
a docstring.

## Paper Broker Simulator (Stage 5)

`app/broker/` is a fully offline, deterministic (given a seed) simulator
-- no network, no real Alpaca connection. It exists so the Trading Engine
(Stage 6) can be built and tested against a realistic broker contract
before any real broker integration exists (Stage 9). It never reads the
wall clock -- every call takes an explicit `now`, exactly like the
backtester.

- **Rejections** happen synchronously at submission: invalid quantity, no
  market data for the symbol, insufficient buying power, or a sell that
  would exceed shares held (this system never shorts -- a second,
  broker-level backstop behind the Risk Engine's own check).
- **Fills never happen inside `submit_order`.** An accepted order sits at
  `NEW` until the caller calls `advance_time(now)`, which resolves any
  order whose scheduled fill time has arrived -- modeling a real broker's
  asynchronous acknowledge-then-fill flow instead of an instant fill that
  would go untested until Stage 9.
- **Latency** (`app/broker/latency.py`) controls how long an order waits
  before its first fill attempt: `ZeroLatency`, `FixedLatency`, or
  `RandomLatency` (seeded, so tests stay deterministic).
- **Partial fills** (`app/broker/fills.py`) control how much of the
  remainder fills per attempt: `FullFillModel` (default) or
  `PartialFillModel`/`RandomPartialFillModel`, which fill a fraction of
  what's left each attempt and finish off the remainder once it drops
  below a configurable dust threshold, rather than shrinking forever.
- Fill prices reuse `app/backtesting/costs.py`'s `SlippageModel` --
  the same cost model backtests already use, applied at whatever price is
  current *at fill time*, not at submission time.
