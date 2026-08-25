# trading_bot

A 24/7 autonomous algorithmic trading system for US equities/ETFs (long-only,
diversified trend/momentum), built on Alpaca, SQLite/SQLAlchemy, and FastAPI.

Built stage by stage; see `BUILD ORDER` in the project brief. **Stage 1
(scaffolding, config, mode switch) and Stage 2 (strategy math spec) are
done.** Stages 3-12 are not implemented yet.

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

## Research

`research/stage2_strategy_math_spec.ipynb` is the Stage 2 deliverable: the
trend/momentum signal math (trend filter, vol-adjusted momentum score,
selection with a turnover buffer, inverse-vol position sizing), justified,
and validated against synthetic data. No production strategy code exists
yet — that starts once the backtester (Stage 3) can validate this spec
against real historical data. `research/_build_notebook.py` regenerates
the notebook if it needs edits (`python _build_notebook.py`, then
`jupyter nbconvert --to notebook --execute --inplace stage2_strategy_math_spec.ipynb`).
