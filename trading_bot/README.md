# trading_bot

A 24/7 autonomous algorithmic trading system for US equities/ETFs (long-only,
diversified trend/momentum), built on Alpaca, SQLite/SQLAlchemy, and FastAPI.

Built stage by stage; see `BUILD ORDER` in the project brief. **All 12
stages are done** (scaffolding/config, strategy math spec, backtesting
engine, risk engine, paper broker simulator, trading engine, dashboard,
monitoring & alerts, real Alpaca adapter, security & failure testing,
extended paper-trading deployment against live market data, and the
live-trading readiness checklist). Stage 12 is deliberately not code —
see [`LIVE_TRADING_CHECKLIST.md`](LIVE_TRADING_CHECKLIST.md) before ever
setting `TRADING_MODE=LIVE`.

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

In `PAPER` or `APPROVAL` mode this starts immediately and runs forever
(heartbeat, fill-polling, and monthly rebalance jobs against real Alpaca
paper-account market data — see **Extended paper-trading deployment**
below). In `LIVE` mode it will print an account/risk-limit banner and
block on a typed confirmation before doing the same against the real
account. Stop with Ctrl+C (or a service stop) for a clean shutdown.

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

`tests/test_broker_alpaca.py::test_submit_order_non_api_error_propagates_never_fabricates_rejection`
is the load-bearing test for Stage 9: only Alpaca's own `APIError` (a
definitive broker verdict) may be converted into a locally-recorded
REJECTED order — a network failure, timeout, or any other exception must
propagate uncaught rather than being silently guessed at.

Run the (real-network, non-deterministic, not part of the test suite)
Alpaca paper-account sanity check — requires real credentials in `.env`:

```powershell
python scripts\run_alpaca_broker_demo.py
python scripts\run_alpaca_broker_demo.py --submit-test-order AAPL
```

`tests/test_security_no_secrets_in_logs.py::test_telegram_failure_never_logs_the_bot_token`
is the load-bearing test for Stage 10: it proves a real vulnerability
found and fixed this stage — the Telegram bot token is embedded directly
in the request URL, and network exceptions commonly echo that URL back in
their own message, so the old `logger.exception(...)` call would have
leaked it into the log file on any connection failure. It's parametrized
over several realistic exception messages, asserting the token never
appears in any log record, formatted or not.

`tests/test_scheduling.py`'s job-failure tests are the load-bearing ones
for Stage 11: they prove each scheduled job catches its own exceptions
and alerts through the engine's AlertManager, rather than relying on
APScheduler to surface them (it doesn't — see the Stage 11 section
below).

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

## Real Alpaca adapter (Stage 9)

`app/broker/alpaca.py`'s `AlpacaBroker` implements the exact same
interface as the Stage 5 `PaperBroker` simulator (`submit_order`,
`advance_time`, `cancel_order`, `get_order`, `get_positions`,
`get_account`) — so `TradingEngine`, `OrderManager`, `Portfolio`, and
startup reconciliation all work completely unchanged whether they're
wired to the local simulator (used by tests and the demo scripts) or this
class talking to real Alpaca. Per the confirmed architecture, **PAPER and
LIVE trading run through this identical class** — `app/broker/factory.py`
is the one place that decides which Alpaca endpoint an instance points
at, driven entirely by `settings.trading_mode` (`Settings.alpaca_base_url`,
already established in Stage 1).

- The adapter depends on alpaca-py's `TradingClient` through a narrow
  `AlpacaTradingClient` Protocol, so every test fakes it completely — no
  real network calls, no real credentials, anywhere in the test suite.
- **Only Alpaca's own `APIError`** (a definitive "the broker refused this
  order" answer — bad symbol, insufficient buying power, market closed,
  etc.) is converted into a locally-recorded `REJECTED` order. Any other
  exception (a network timeout, a dropped connection, a 5xx) is left to
  propagate uncaught rather than being silently guessed at — an unknown
  outcome must surface as a crash for Stage 8's watchdog to alert on and
  retry, never as a fabricated verdict that could hide a real order or
  invite a double-submit on retry.
- `get_order()` translates a 404-style `APIError` into a `KeyError`, so
  `app/database/reconciliation.py`'s "this order is unknown to the
  broker" branch works identically for both brokers.
- Alpaca's order status has many more in-flight states than our own
  `OrderStatus`; anything not explicitly recognized defaults to `NEW`
  (still open) rather than being mistaken for filled or canceled in
  either direction.
- Alpaca's REST responses return numeric fields (`qty`, `cash`, `equity`,
  ...) as strings; every one is explicitly `float()`'d crossing into our
  domain models (`BrokerPosition`, `AccountSnapshot`, `Order`).
- `AccountSnapshot` gained an `account_id` field. `app/main.py`'s LIVE-mode
  path now fetches a **real** account snapshot before ever showing the
  typed-confirmation banner — a gap flagged since Stage 1, when
  `account_snapshot` was always `None` because no broker adapter existed
  to ask. If the broker can't be reached, startup now aborts *before* the
  banner is shown, rather than proceeding with "UNKNOWN" placeholders.
- Full scheduler / live rebalance-loop wiring (calling
  `TradingEngine.run_rebalance_cycle` on a schedule against real market
  data) is deliberately deferred to Stage 11 — this stage is the adapter
  itself, proven correct in isolation.

## Security & failure testing (Stage 10)

Deliberate fault injection, not new features — the point of this stage is
finding and closing real gaps, not building more surface area. Four found
and fixed:

- **Secret leak in logs (security).** The Telegram bot token is embedded
  directly in the request URL
  (`https://api.telegram.org/bot<TOKEN>/sendMessage`). Network-layer
  exceptions (connection errors, timeouts) commonly echo the offending URL
  back in their own message — so `TelegramNotifier.send()`'s old
  `logger.exception(...)` call on failure would have written the token
  straight into the log file on any connection problem. Fixed to log only
  the exception's type name, never its message or traceback. See
  `tests/test_security_no_secrets_in_logs.py`.
- **Duplicate orders on cycle replay (failure).** `run_rebalance_cycle`'s
  target weights/deltas are derived from the broker's current positions,
  which don't yet reflect an order that's accepted but not filled.
  Re-running a cycle before the previous one's orders resolve — a
  crash-restart replay, a scheduler double-fire — would recompute the
  identical delta and submit a duplicate order on top of the first.
  `TradingEngine` now refuses to submit new orders while any local order
  is still open, alerting instead, and picks back up automatically once
  they resolve. See `tests/test_failure_duplicate_orders.py`.
- **Orders lost to a crash between submit and persist (failure — "kill
  the connection mid-order").** The dangerous window isn't a `submit()`
  call that raises (Stage 9 already handles that) — it's the gap between
  `broker.submit_order()` succeeding and the DB write that would have
  recorded it. A process killed in exactly that gap left the local DB with
  zero record the order ever happened, even though the broker has it.
  Position reconciliation already self-healed from this (broker positions
  always win), but the order audit trail didn't. Both brokers gained
  `list_orders(since)`, and `reconcile_startup_state()` now cross-checks
  the broker's recent orders (bounded to a 1-day lookback) against what
  the local DB actually knows, recovering anything missing. See
  `tests/test_failure_broker_crash_recovery.py`.
- **Stale/missing market data (failure).** A live-quote feed going dark
  for a symbol, or entirely, must never crash the cycle or silently price
  something at zero. `Portfolio.current_state()` already fell back to a
  position's average cost when its price lookup returns `None`; a price
  lookup that *raises* (a genuinely broken data source, not just a gap) is
  left to propagate rather than being masked — those are different
  failure modes and deserve different handling. `run_rebalance_cycle`
  already fell back to the last known historical close when a live quote
  is missing for a proposed order. Both fallbacks are now explicitly
  proven, not just incidental. See `tests/test_failure_stale_data.py` and
  the new tests in `tests/test_portfolio.py`.

General review also confirmed: all database access goes through
SQLAlchemy's query builder (no raw/string-formatted SQL anywhere, so no
SQL-injection surface), `config/risk_limits.yaml` is loaded with
`yaml.safe_load` (not `yaml.load`), and the dashboard's Jinja2 templates
use the framework's default autoescaping (no `|safe` filters anywhere).

## Extended paper-trading deployment (Stage 11)

Everything built through Stage 10 has proven the pipeline correct; this
stage wires it to actually run, continuously, against real market data.
`python -m app.main` in PAPER mode now starts the real 24/7 loop, not
just the safety gate — the same `run()` path LIVE mode uses once
confirmed, per the confirmed "same code path, only endpoint differs"
architecture.

- **`app/strategy/universe.py`**: the Stage 2 research notebook's
  recommended v1 basket — 11 SPDR sector ETFs, broad market (SPY/QQQ/IWM),
  international (EFA/EEM), bonds (TLT/IEF/SHY), and alternatives
  (GLD/DBC/VNQ). 22 liquid, diversified ETFs, not individual equities, per
  that notebook's reasoning (structural diversification, no single-name
  risk, deep liquidity, a trivial defensive leg via SHY).
- **`app/market_data/alpaca_bars.py`**: `AlpacaMarketData` fetches daily
  bars (split/dividend-adjusted, `Adjustment.ALL` — a momentum strategy
  must never see a false signal break from an ETF distribution) shaped
  into the same close-price DataFrame the strategy/backtester already
  expect, plus latest-trade prices for order pricing. Depends on
  alpaca-py's data client through a narrow Protocol — fully faked in
  tests, same pattern as the Stage 9 broker adapter.
- **`app/market_data/live_price_cache.py`**: `TradingEngine.price_lookup`
  is captured once at construction time and can't be swapped per cycle.
  `LivePriceCache` is the small mutable cell that bridges this — the
  scheduler calls `update()` with a fresh quote snapshot immediately
  before each rebalance cycle, and the engine's `price_lookup` reads
  through `get()`. This isn't just cosmetic: `Position.unrealized_pnl_pct`
  drives the Risk Engine's anti-martingale rule, so how fresh this cache
  is matters for a real safety check, not only for display.
- **`app/scheduling.py`**: `TradingScheduler` wraps three APScheduler
  jobs — `heartbeat` and `poll_fills` on fixed short intervals (so
  heartbeat keeps landing even on days the strategy does nothing), and
  `rebalance` firing every weekday at a configured time but only actually
  doing anything on the first NYSE session of the month (checked against
  `app/backtesting/calendar.py`'s real trading-calendar logic, not a cron
  expression that has to separately encode market holidays). Runs in
  `America/New_York` regardless of the host machine's local timezone
  setting, since a Windows desktop isn't guaranteed to be set to Eastern.
- **Critical correctness detail, found by actually reading APScheduler's
  own executor source before wiring this**: APScheduler catches *every*
  exception a job raises internally, to keep its own loop alive, and
  never re-raises it to whatever called `scheduler.start()`. That means
  wrapping `start()` in Stage 8's crash-restart watchdog (which
  `app/main.py` still does, as a backstop against the scheduler's own
  internals failing) gives **zero** protection against a job itself
  failing — a broken `run_rebalance` would otherwise disappear into
  APScheduler's own internal logger and nowhere else. Each job method in
  `TradingScheduler` therefore catches its own exceptions and explicitly
  alerts through the engine's `AlertManager` — that is the real safety
  net for job failures.
- **`app/bootstrap.py`**: the one place that assembles the real broker,
  market data client, risk limits (config + yaml), alerts, and database
  session into a `TradingScheduler` from `Settings` — kept separate from
  `app/main.py` so it can be constructed and inspected in tests without
  ever calling the blocking `scheduler.start()`.
- **`app/main.py`**: `run(settings)` builds the scheduler, runs startup
  reconciliation (still mandatory, still broker-authoritative, per every
  prior stage), then runs the scheduler forever. A reconciliation failure
  (e.g. bad credentials, no network) is deliberately left to crash loudly
  here rather than being caught and retried — the non-negotiable rule is
  "reconcile before any trading," so if that can't succeed the process
  must not proceed, and a loud crash (visible to NSSM, to a human) is the
  correct failure mode, not a silent retry loop.
- Approximation worth being honest about: the backtester assumes a fill
  exactly at the session's opening price. A live market order fired a few
  minutes after the open (`REBALANCE_HOUR`/`REBALANCE_MINUTE`, default
  9:35 ET) fills at whatever price is then prevailing, not literally the
  opening print — a real, small, permanent divergence from the backtest's
  idealization, not something to pretend away.

New config: `HEARTBEAT_INTERVAL_SECONDS`, `POLL_FILLS_INTERVAL_SECONDS`,
`REBALANCE_HOUR`, `REBALANCE_MINUTE` (see `.env.example`).

24 new tests (284 total), all against fakes/stubs for the Alpaca data
client and a stub market-data source — plus one true end-to-end
integration test (`tests/test_scheduling_integration.py`) that drives a
real `TradingEngine` + `PaperBroker` through `TradingScheduler.run_rebalance()`
and confirms an order is actually submitted and, once polled, filled —
proving the full scheduler → engine → strategy → risk → broker pipeline
works together, not just each piece in isolation.

Not done here, deliberately: this stage makes the loop *run*; it doesn't
decide *when* it's safe to point at a real Alpaca paper account and leave
it running unattended for days, or what "extended" should mean in
practice (how long, what to watch, when to call it validated). That
judgment, and Stage 12's live-trading readiness checklist, are yours.

## Live-trading readiness checklist (Stage 12)

[`LIVE_TRADING_CHECKLIST.md`](LIVE_TRADING_CHECKLIST.md) is the final
deliverable of the build order, and it is deliberately not code — every
other stage produced a module and a test suite; this one is a decision
document. It covers: replacing the placeholder risk/capital numbers that
have been flagged as unresolved since Stage 1, verifying live credentials
and alerting without risking a real order, what to look for in an
extended paper-trading track record before trusting it, operational and
kill-switch readiness, an explicit list of what this system does **not**
do, and everything outside this codebase's scope entirely (legal, tax,
personal risk tolerance).

Nothing in this repository will ever set `TRADING_MODE=LIVE` or type the
`ENABLE LIVE TRADING` confirmation phrase on your behalf. That decision,
and the judgment behind it, is yours alone.
use the framework's default autoescaping (no `|safe` filters anywhere).
