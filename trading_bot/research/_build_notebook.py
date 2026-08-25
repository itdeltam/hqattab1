"""One-off generator for stage2_strategy_math_spec.ipynb. Not part of the
app; run once to (re)build the notebook, then delete or leave as a record
of how it was produced."""
import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []

def md(text):
    cells.append(nbf.v4.new_markdown_cell(text))

def code(text):
    cells.append(nbf.v4.new_code_cell(text))

md(r"""# Stage 2 — Strategy Math Spec: Diversified Trend/Momentum System

This notebook is a **research spec, not production code**. It defines the
signal math for the trading system, justifies each choice, and validates
the formulas against synthetic data with known properties before any of
this logic gets ported into `app/strategy/`.

Scope per the project brief: US equities/ETFs, **long-only**, diversified
trend/momentum (not HFT, not ML-first).
""")

md(r"""## 1. Universe

**Recommendation for v1: a fixed basket of ~25-30 liquid, diversified US
sector and asset-class ETFs** (e.g. the 11 SPDR sector ETFs, broad market
ETFs like SPY/QQQ/IWM, international EFA/EEM, bonds TLT/IEF/SHY, and
alternatives GLD/DBC/VNQ), rather than individual equities, for four
reasons:

1. **Diversification is structural, not statistical.** An ETF universe is
   diversified by construction; a stock-picking momentum system needs a
   much larger universe and more careful correlation control to avoid
   concentration in one theme (e.g. all-mega-cap-tech momentum).
2. **No idiosyncratic single-name risk.** No earnings gaps, no M&A halts,
   no single-name blowups — important for an unattended 24/7 system.
3. **Liquidity and clean corporate actions.** Sector/asset-class ETFs are
   deep and simple to adjust for splits/distributions; individual equities
   need point-in-time index-membership handling to avoid survivorship
   bias in backtests (Stage 3).
4. **A defensive/cash-equivalent leg is trivial**: SHY or BIL (short-duration
   Treasuries) serves as the "risk-off" holding when the trend filter
   rejects most of the universe (see §3).

Individual equities can be added later as a second sleeve using the same
math — nothing here is ETF-specific — but v1 ships with the simpler,
structurally-diversified universe.
""")

md(r"""## 2. Signal 1 — Absolute Momentum / Trend Filter

Each asset must independently earn the right to be *eligible* for
selection. An asset is **eligible** (in an uptrend) iff **both**:

- Trailing 12-month (252 trading day) total return is positive, **and**
- Current price is above its 200-day simple moving average.

**Why both conditions, not just one:** the 12-1 month return condition is
the classic absolute-momentum filter (Antonacci); the 200-day SMA
condition is the classic trend-following filter (Faber's timing model).
They usually agree, but requiring both reduces whipsaw around a single
threshold and is a standard robustness technique — two independent, cheap
signals rather than one signal parameterized two ways.

**Why this matters for the long-only constraint:** this is the mechanism
that keeps the system out of confirmed downtrends without ever going
short. Assets that fail this filter are simply excluded from selection —
capital rotates to the defensive leg (§3) instead.
""")

code(r"""import numpy as np
import pandas as pd

rng = np.random.default_rng(seed=7)

# True where the asset is eligible (in an uptrend). NaN-safe: False wherever
# there isn't enough history yet, never raises.
def trend_filter(prices: pd.Series, sma_window: int = 200, mom_window: int = 252) -> pd.Series:
    sma = prices.rolling(sma_window).mean()
    trailing_return = prices / prices.shift(mom_window) - 1
    eligible = (prices > sma) & (trailing_return > 0)
    return eligible.fillna(False)
""")

md(r"""## 3. Signal 2 — Relative (Cross-Sectional) Momentum Score

Among eligible assets, rank by a **volatility-adjusted, multi-lookback
momentum score**:

```
score = mean(return_63d, return_126d, return_252d) / realized_vol_63d
```

where each lookback return **skips the most recent 5 trading days**
(`shift(5)` before differencing).

**Why an ensemble of lookbacks (3/6/12 month) instead of one "best"
lookback:** picking a single optimal lookback is a classic overfitting
trap — it fits whatever regime is in the backtest sample. Averaging three
lookbacks is a standard robustness technique (used in commercial
dual-momentum and managed-futures models) that trades a small amount of
signal purity for a large reduction in parameter sensitivity.

**Why skip the most recent 5 days:** short-horizon reversal (bid-ask
bounce, 1-week mean reversion) is a well-documented contaminant of
momentum signals (Jegadeesh & Titman). Skipping the most recent week is
cheap insurance against it.

**Why divide by realized volatility:** raw returns favor high-volatility
assets by construction (a leveraged-like ETF will show larger raw moves
in either direction). Dividing by trailing realized vol turns the score
into a Sharpe-like, cross-sectionally comparable ranking, so the ranking
reflects trend *quality* rather than raw magnitude.
""")

code(r"""# Annualized realized volatility of daily returns.
def realized_vol(prices: pd.Series, window: int = 63) -> pd.Series:
    return prices.pct_change().rolling(window).std() * np.sqrt(252)


# Volatility-adjusted, multi-lookback momentum score. NaN wherever there
# isn't enough history for the longest lookback yet.
def momentum_score(
    prices: pd.Series,
    lookbacks=(63, 126, 252),
    skip: int = 5,
    vol_window: int = 63,
) -> pd.Series:
    rets = []
    for lb in lookbacks:
        r = prices.shift(skip) / prices.shift(skip + lb) - 1
        rets.append(r)
    # skipna=False deliberately: until every lookback has full history, a
    # partial average would silently mix a 1-lookback score with a
    # 3-lookback score, which are not comparable across assets/dates.
    avg_ret = pd.concat(rets, axis=1).mean(axis=1, skipna=False)
    vol = realized_vol(prices, vol_window)
    return avg_ret / vol
""")

md(r"""## 4. Selection Rule

1. Compute `trend_filter` and `momentum_score` for every asset in the
   universe as of the rebalance date.
2. Restrict to assets where `trend_filter` is True — this is the eligible
   set.
3. Rank the eligible set by `momentum_score` descending.
4. Select the top **K** (v1 default: K = 6 out of a ~25-30 name universe —
   concentrated enough to matter, diversified enough that one name's
   reversal doesn't dominate the portfolio).
5. **If fewer than K assets are eligible** (broad market downturn), the
   remaining allocation goes to the defensive leg (SHY/BIL), not into
   marginal/ineligible names. This is what keeps a long-only trend system
   safe in a bear market — it is not the Risk Engine's job to catch this;
   it's built into the strategy's selection rule itself.

**Turnover control — a buffer/hysteresis zone:** without it, small rank
changes near the K-th cutoff cause needless trading every rebalance. Rule:
an asset **already held** is kept if its current rank is within `K +
buffer` (v1 default buffer = 4, i.e. keep if still ranked ≤ 10 when K=6).
New assets are only added to fill slots actually vacated. This is a
standard technique in momentum strategy implementation (reduces turnover
substantially with a small, well-understood cost to signal purity).
""")

code(r"""# One rebalance step. `scores`/`eligible` are cross-sectional (one value
# per asset) as of the rebalance date.
def select_with_buffer(
    scores: pd.Series,
    eligible: pd.Series,
    current_holdings: set,
    k: int = 6,
    buffer: int = 4,
) -> set:
    ranked = scores[eligible].sort_values(ascending=False)
    rank_of = {ticker: i + 1 for i, ticker in enumerate(ranked.index)}

    kept = {t for t in current_holdings if rank_of.get(t, np.inf) <= k + buffer}

    new_selections = set(kept)
    for ticker in ranked.index:
        if len(new_selections) >= k:
            break
        new_selections.add(ticker)

    return new_selections


# Long-only, no-leverage weights inversely proportional to trailing vol,
# normalized to sum to 1. Lower-vol names get more weight, spreading risk
# contribution more evenly than equal-weighting would.
def inverse_vol_weights(vols: pd.Series) -> pd.Series:
    inv = 1.0 / vols
    return inv / inv.sum()
""")

md(r"""## 5. Position Sizing — Inverse-Volatility Weighting

Within the selected top-K, weight positions **inversely proportional to
trailing 63-day realized volatility**, normalized to sum to 1 (fully
invested across the sleeve; no leverage, matching the project's no-leverage
default). This is a lightweight risk-parity approximation: it prevents one
high-vol "hot" name from dominating portfolio risk the way equal-weighting
would.

Every weight is still subject to the Risk Engine's `MAX_POSITION_PCT`
cap (Stage 4) — the strategy proposes these weights, the Risk Engine can
veto or clip them. That separation is a non-negotiable project constraint,
not a detail of this spec.

**Deferred to a later iteration, not v1:** portfolio-level volatility
targeting (scaling total invested fraction up/down to hit a target
annualized portfolio vol). v1 is always fully invested across whatever the
selection rule picks (subject to the defensive-leg fallback in §4) —
simpler to reason about and to backtest correctly first.
""")

md(r"""## 6. Rebalance Schedule

**Monthly, on the first trading day of the month.** Momentum signals decay
over weeks, not days; monthly rebalancing is the standard cadence in the
momentum literature and keeps turnover (and commissions/slippage, modeled
in Stage 3) low. Weekly or daily rebalancing would mostly add transaction
costs and whipsaw, not signal.

Mid-month risk events (a sharp drawdown in a held position) are explicitly
**not** handled by the strategy — that is the Risk Engine's kill-switch
responsibility (Stage 4). Keeping that logic out of the strategy layer is
what lets the Risk Engine veto *any* strategy decision without exception.
""")

md(r"""## 7. No-Look-Ahead-Bias Rules (binding on the Stage 3 backtester)

These aren't optional style points — they're the rules Stage 3 must
enforce mechanically:

1. A signal computed "as of" date *t* may only use price data through the
   close of *t − 1*.
2. Orders implied by a signal as of *t* execute at *t*'s open (next bar
   after the signal), never at *t*'s close or earlier.
3. All return/vol calculations use **adjusted** close (splits + dividends),
   applied consistently — never mixing adjusted and raw series.
4. Universe membership must be point-in-time. Low risk for a fixed ETF
   basket (ETFs essentially never disappear); becomes mandatory if an
   equities sleeve is added later (must use historical index membership,
   not today's constituents, to avoid survivorship bias).
""")

md(r"""## 8. Fixed Parameter Set (for Stage 3 to backtest, not to curve-fit)

| Parameter | v1 value | Role |
|---|---|---|
| Trend filter SMA window | 200 days | Absolute trend filter |
| Trend filter momentum window | 252 days | Absolute momentum filter |
| Momentum lookbacks | 63 / 126 / 252 days | Ensemble relative momentum |
| Momentum skip window | 5 days | Avoid short-term reversal |
| Volatility window | 63 days | Vol-adjustment & position sizing |
| Top-K | 6 | Selection breadth |
| Rank buffer | 4 (i.e. keep ≤ rank 10) | Turnover control |
| Rebalance frequency | Monthly | Signal decay vs. transaction cost |
| Defensive asset | SHY (or BIL) | Risk-off leg when eligible count < K |

Deliberately few knobs. Stage 3 should validate this fixed set
out-of-sample rather than search over it — searching this parameter space
against the same backtest data it's validated on is how trend-following
backtests get quietly overfit.

**Correlation / concentration limits are explicitly out of scope here** —
that's a Risk Engine concern (Stage 4: the Risk Engine must be able to
veto a Strategy-proposed trade, including for correlation/concentration
reasons the strategy layer doesn't model). This spec only produces
proposed weights; it does not enforce portfolio-level constraints.
""")

md(r"""## 9. Validation on Synthetic Data

Five synthetic price series with known, designed-in properties, so we can
assert the formulas behave the way §2-§5 claim they should — before any of
this touches real market data (Stage 3) or production code (later stages).
""")

code(r"""n_days = 500
dates = pd.bdate_range("2022-01-03", periods=n_days)

# Deterministic exponential trend with i.i.d. (non-cumulative) multiplicative
# daily noise. Unlike a GBM random walk, the noise here can't permanently
# drag the level away from the trend -- which is the point: these fixtures
# are meant to reliably exhibit "this is an uptrend" / "this is a downtrend"
# regardless of random seed, while still carrying a realistic, controllable
# day-to-day volatility for the vol-adjustment checks below.
def trending_series(index, annual_drift, annual_vol, s0=100.0, seed=0):
    rng = np.random.default_rng(seed)
    n = len(index)
    t = np.arange(n)
    trend = s0 * np.exp(annual_drift * t / 252)
    daily_vol = annual_vol / np.sqrt(252)
    noise = rng.normal(0, daily_vol, n)
    return pd.Series(trend * (1 + noise), index=index)

prices = pd.DataFrame({
    "UP_STEADY":    trending_series(dates, annual_drift=0.18, annual_vol=0.10, seed=1),  # strong trend, low vol
    "UP_VOLATILE":  trending_series(dates, annual_drift=0.18, annual_vol=0.35, seed=2),  # same drift, high vol
    "FLAT_CHOPPY":  trending_series(dates, annual_drift=0.00, annual_vol=0.20, seed=3),  # no trend
    "DOWN_TREND":   trending_series(dates, annual_drift=-0.20, annual_vol=0.15, seed=4), # confirmed downtrend
    "SHY":          trending_series(dates, annual_drift=0.02, annual_vol=0.02, seed=5),  # defensive leg proxy
})

prices.tail()
""")

code(r"""eligible = prices.apply(trend_filter)
scores = prices.apply(momentum_score)

# --- Assertion 1: not enough history yet must be ineligible, not an error ---
assert not eligible.iloc[:200].any().any(), "Nothing should be eligible before 200d history exists"
assert scores.iloc[:252].isna().all().all(), "Momentum score needs 252d history; must be NaN, not a wrong number"

as_of = dates[-1]
elig_today = eligible.loc[as_of]
scores_today = scores.loc[as_of]

# --- Assertion 2: the trend filter correctly separates up from down trends ---
assert elig_today["UP_STEADY"] and elig_today["UP_VOLATILE"], "Both up-trending assets should be eligible"
assert not elig_today["DOWN_TREND"], "Confirmed downtrend must not be eligible"
print("Eligible as of", as_of.date(), ":", list(elig_today[elig_today].index))
""")

code(r"""# --- Assertion 3: vol-adjustment matters — equal drift, different vol,
# so UP_STEADY (low vol) must outrank UP_VOLATILE (high vol) on the score,
# even though raw total return over the period is similar by construction ---
raw_return = prices.loc[as_of] / prices.iloc[0] - 1
print("Raw total return  :", raw_return[["UP_STEADY", "UP_VOLATILE"]].round(3).to_dict())
print("Vol-adjusted score:", scores_today[["UP_STEADY", "UP_VOLATILE"]].round(3).to_dict())

assert scores_today["UP_STEADY"] > scores_today["UP_VOLATILE"], (
    "Equal-drift, lower-vol asset must score higher after vol-adjustment"
)
""")

code(r"""# --- Assertion 4: selection + inverse-vol weighting ---
current_holdings = {"UP_VOLATILE", "DOWN_TREND"}  # DOWN_TREND no longer eligible -> must be dropped
selected = select_with_buffer(scores_today, elig_today, current_holdings, k=2, buffer=1)
print("Selected:", selected)

assert "DOWN_TREND" not in selected, "An asset that lost eligibility must never be kept"
assert "UP_STEADY" in selected, "The best-ranked eligible asset must be selected"

vols_today = prices.pct_change().rolling(63).std().loc[as_of] * np.sqrt(252)
weights = inverse_vol_weights(vols_today[list(selected)])
print("Weights:", weights.round(3).to_dict())

assert abs(weights.sum() - 1.0) < 1e-9, "Weights must sum to exactly 1 (fully invested, no leverage)"
if "UP_STEADY" in selected and "UP_VOLATILE" in selected:
    assert weights["UP_STEADY"] > weights["UP_VOLATILE"], (
        "Lower-vol name must receive a larger weight under inverse-vol sizing"
    )
""")

code(r"""# --- Assertion 5: buffer/hysteresis actually reduces turnover ---
# A held name ranked just outside top-K but inside the buffer must be kept;
# the same name must be dropped once buffer is set to 0. Rather than assume
# UP_VOLATILE's exact rank, derive it, then place k just below that rank so
# this test exercises the buffer boundary regardless of the scores' exact
# values (only assertion 3 -- UP_STEADY outranks UP_VOLATILE -- is assumed,
# which guarantees UP_VOLATILE's rank among eligible assets is >= 2).
holdings = {"UP_VOLATILE"}

ranked_eligible = scores_today[elig_today].sort_values(ascending=False)
up_volatile_rank = list(ranked_eligible.index).index("UP_VOLATILE") + 1
k = up_volatile_rank - 1  # UP_VOLATILE sits exactly one rank outside top-k

kept_with_buffer = select_with_buffer(scores_today, elig_today, holdings, k=k, buffer=1)
kept_without_buffer = select_with_buffer(scores_today, elig_today, holdings, k=k, buffer=0)

print(f"UP_VOLATILE rank={up_volatile_rank}, k={k}")
print("k=%d, buffer=1:" % k, kept_with_buffer)
print("k=%d, buffer=0:" % k, kept_without_buffer)

assert "UP_VOLATILE" in kept_with_buffer, "Buffer should retain a marginally-ranked existing holding"
assert "UP_VOLATILE" not in kept_without_buffer, "Without a buffer, rank must strictly decide"

print()
print("All Stage 2 formula checks passed.")
""")

md(r"""## 10. What Stage 3 Inherits From This Spec

Stage 3 (backtesting engine) must implement exactly the functions above
(`trend_filter`, `momentum_score`, `select_with_buffer`,
`inverse_vol_weights`) against real daily bar data, plus:

- Commission and slippage modeling
- Enforcing the point-in-time / no-look-ahead rules from §7 mechanically
  (not just as a comment — e.g. the backtest loop must physically not have
  access to future rows when computing a signal)
- Market-hours/calendar handling (`pandas_market_calendars`, already
  chosen) so rebalance dates fall on actual trading days

Nothing here is implemented in `app/strategy/` yet, per the brief for this
stage — that happens once the backtester (Stage 3) exists to validate it
against real historical data.
""")

nb["cells"] = cells
nbf.write(nb, "stage2_strategy_math_spec.ipynb")
print("wrote stage2_strategy_math_spec.ipynb")
