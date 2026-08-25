# trading_bot

A 24/7 autonomous algorithmic trading system for US equities/ETFs (long-only,
diversified trend/momentum), built on Alpaca, SQLite/SQLAlchemy, and FastAPI.

Built stage by stage; see `BUILD ORDER` in the project brief. **Stages 1-8
(scaffolding/config, strategy math spec, backtesting engine, risk engine,
paper broker simulator, trading engine, dashboard, monitoring & alerts)
are done.** Stages 9-12 are not implemented yet.

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
- On every startup, local DB state is reconciled against the broker's
  actual account/positions/orders before any trading is allowed. Broker
  state is always authoritative — see `app/database/reconciliation.py`.

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

## Dashboard

Runs as its own process, separate from the trading loop, reading only
the shared SQLite database:

```powershell
uvicorn app.web.main:app --reload
```

Then open http://127.0.0.1:8000/. Read-only — see the Dashboard section
below.

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

`tests/test_trading_engine_integration.py` is the load-bearing test suite
for Stage 6: it proves an absurdly tight position cap results in the
Risk Engine fully vetoing every proposed order and `submitted_orders`
staying empty — there's no code path from a Strategy decision to the
broker that skips risk evaluation.

Run a demo full-cycle trade (reconcile, propose, risk-check, submit,
poll fills) against synthetic data:

```powershell
python scripts\run_trading_engine_demo.py
```

`tests/test_web_routes.py::test_every_route_is_read_only` is the
load-bearing test for Stage 7: it inspects the actual FastAPI route table
and asserts nothing but GET (and the framework's own HEAD/OPTIONS) is
ever registered, anywhere in the app.

`tests/test_alerts_never_crash_the_caller.py` is the load-bearing test
suite for Stage 8: it proves alerting can never take down the loop it's
watching — `AlertManager.notify()` swallows every sink exception (even
when *every* sink is broken), and the crash-restart watchdog keeps
restarting a repeatedly-crashing target even when the act of alerting
about each crash itself blows up.

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

## Trading Engine (Stage 6)

`app/trading_engine.py` wires everything built so far into one cycle:
**Strategy → Portfolio → Risk Engine → Order Manager → Broker**, with
mandatory startup reconciliation. Every new piece this stage added:

- **`app/database/`** — SQLAlchemy models + SQLite WAL setup. The database
  is a *mirror* of broker truth, never an independent ledger: positions
  and orders are always overwritten from what the broker reports, so
  local state can never drift out of sync with the account that actually
  holds the money. What it uniquely owns is history — an append-only
  equity-snapshot log, which is how day-start/week-start/peak equity
  survive an app restart for the Risk Engine's loss-limit and drawdown
  checks.
- **`app/database/reconciliation.py`** — `reconcile_startup_state()`:
  overwrites local positions from `broker.get_positions()` wholesale, and
  re-syncs any DB-tracked open order against `broker.get_order()`
  individually (the paper broker has no bulk order listing yet; a real
  Alpaca adapter's bulk listing in Stage 9 slots into the same function
  without changing this contract). Every mismatch found is logged as a
  discrepancy, not silently corrected.
- **`app/portfolio/`** — builds the Risk Engine's `PortfolioState`
  snapshot by reading the broker fresh every time (never its own cached
  ledger) plus the DB's equity history.
- **`app/execution/`** — `OrderManager` submits Risk-Engine-approved
  orders to the broker and keeps DB order records in sync; never retries
  a rejected order on its own.
- **`app/strategy/rebalancing.py`** — the target-weight and order-sizing
  math, extracted out of the backtester (Stage 3) so both it and the
  Trading Engine call the identical, single-sourced logic instead of two
  copies that could quietly diverge.

The current momentum-sleeve holdings used for the selection buffer
(Stage 2's turnover-reduction rule) are derived from actual broker
positions each cycle, not tracked as separate state — one less ledger
that could disagree with reality.

No real market data or scheduling exists yet, so `app/main.py` is
unchanged from Stage 1 — running the Trading Engine for real needs a live
price feed (Stage 9) and a scheduler (APScheduler, not yet wired in) to
call it on a schedule. Everything above is proven with synthetic data via
`scripts/run_trading_engine_demo.py` and the test suite.

## Dashboard (Stage 7)

`app/web/` is a **read-only** FastAPI + server-rendered HTML/HTMX
dashboard, per the confirmed architecture. It runs as its own process,
entirely separate from the Trading Engine, and only ever reads the shared
SQLite database (WAL mode lets both processes touch it concurrently) —
it never imports a live broker or engine instance.

- **Every route is a GET.** There is no POST/PUT/PATCH/DELETE anywhere in
  `app/web/main.py` — nothing on this dashboard can place, cancel, or
  modify a trade, change a risk limit, or touch the trading mode.
  `tests/test_web_routes.py::test_every_route_is_read_only` enforces this
  by inspecting the actual FastAPI route table, not by convention.
- **Panels**: system status (trading mode, last activity, stale-if->15min
  since the last equity snapshot or order update), account (latest
  equity/cash from the equity-snapshot log), positions, recent orders,
  and the currently configured risk limits and strategy parameters.
- **`app/web/data.py`** is a pure read layer — every function reads from
  the database and shapes a view-model; none of them write anything. That
  split is what makes "the dashboard never mutates trading state"
  checkable by reading one file.
- Live price and unrealized P&L are intentionally **not** shown yet —
  there's no live market-data feed until Stage 9, and the dashboard would
  rather show nothing than a fabricated number. It shows exactly what the
  database actually has: quantity, average entry price, and cost basis.
- HTMX auto-refreshes each panel (`hx-trigger="every 10s"`) via small
  partial endpoints (`/partials/system`, `/partials/account`,
  `/partials/positions`, `/partials/orders`) that return just that
  panel's HTML fragment, loaded from a CDN — the dashboard needs internet
  access on first paint (the machine it runs on already does, for pip/apt
  installs).
- Renders correctly on a completely empty database (before the Trading
  Engine has ever run a cycle) — every panel has an explicit empty state
  rather than crashing on missing data.

Run it standalone (see **Dashboard** above) and open
http://127.0.0.1:8000/ — no trading loop needs to be running for the
dashboard to start; it just shows empty-state panels until one is.

## Monitoring & alerts (Stage 8)

Two separate concerns, both designed so a failure in either can never
propagate back into the trading loop they're watching:

- **Heartbeat** (`app/monitoring/heartbeat.py`) is a liveness signal,
  deliberately kept separate from *trading* activity. `TradingEngine`
  records a heartbeat on startup reconciliation and on every rebalance
  cycle; a future scheduler (Stage 9) is expected to call
  `TradingEngine.heartbeat(now)` on a tight, fixed cadence (e.g. every
  60s) independent of whether a rebalance actually happened — that's what
  lets the dashboard tell "engine alive, just idle" (market closed,
  nothing eligible to trade) apart from "engine crashed or hung."
  `HeartbeatMonitor` polls this and fires alerts **only on state
  transitions** (going stale, and recovering) — never once per poll,
  which would just get a channel muted. The dashboard's System panel now
  shows both "Last activity" (existing, trade/equity-based) and "Last
  heartbeat" (new, liveness-based) side by side.
- **Crash-restart** (`app/monitoring/watchdog.py`) is an in-process
  supervisor: `run_with_restart()` calls a target callable in a loop and
  restarts it on any exception, with exponential backoff (capped), up to
  an optional `max_restarts` before giving up and re-raising. This is a
  second line of defense *underneath* the OS-level one (NSSM, per the
  Windows deployment plan) — NSSM restarts the whole process if it dies
  outright; this catches a single bad cycle inside a long-running loop so
  a transient fault doesn't take the whole process down.
- **Telegram** (`app/alerts/telegram.py`) is the delivery channel:
  `TelegramNotifier.send()` never raises — a missing/wrong bot token, no
  network, or Telegram being down all just return `False` instead of
  crashing whatever called it. Not configuring `TELEGRAM_BOT_TOKEN` /
  `TELEGRAM_CHAT_ID` is treated as "alerts not configured," not an error.
  `AlertManager` (`app/alerts/manager.py`) fans an event out to every
  configured sink and always logs, independent of delivery success.
- Startup reconciliation (`app/database/reconciliation.py`) now feeds
  `AlertManager` directly: any discrepancy found between local DB state
  and broker truth fires a `WARNING` alert (self-healing happens either
  way — broker always wins — but a human should know it happened).

Configure `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and
`HEARTBEAT_STALE_SECONDS` in `.env` (see `.env.example`).
