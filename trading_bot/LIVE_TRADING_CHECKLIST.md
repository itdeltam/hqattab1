# Live-Trading Readiness Checklist (Stage 12)

This is the last item in the original build order, and it is deliberately
**not code**. Every other stage in this project produced a module and a
test suite; this one produces a decision. Nothing in this repository will
ever set `TRADING_MODE=LIVE` for you, and nothing will type the
confirmation phrase (`ENABLE LIVE TRADING`) for you — see
`app/startup.py`. That is by design, and it means the decision to go live
is entirely yours, informed by whatever you actually check below rather
than by what the code assumes.

Work through every section. Do not skip to section 9.

## 1. Configuration — real numbers, not placeholders

- [ ] `STARTING_CAPITAL` in `.env` is the actual dollar amount you intend
      to allocate — **not** the `100000` placeholder shipped in
      `.env.example`. This has been an open item since Stage 1 and was
      never resolved during the build; it is the single most important
      box on this list.
- [ ] `MAX_DRAWDOWN_PCT` reflects a drawdown you can tolerate — both
      financially and emotionally — not the `0.15` default left
      unexamined.
- [ ] `MAX_DAILY_LOSS_PCT` / `MAX_WEEKLY_LOSS_PCT` reviewed and
      intentional.
- [ ] `MAX_POSITION_PCT` reviewed — the default allows any single ETF
      position up to 10% of equity.
- [ ] `ALLOW_LEVERAGE` is `false` unless you have a specific, reasoned
      need for leverage. If `true`, `MAX_LEVERAGE` was deliberately
      chosen, not left at a default.
- [ ] `config/risk_limits.yaml` (correlation limits, anti-martingale
      threshold) reviewed.
- [ ] `app/strategy/params.py`'s `StrategyParams` (lookbacks, `top_k`,
      rank buffer) match what was actually validated in backtesting —
      not changed after the fact without re-running the Stage 3 backtest.
- [ ] `app/strategy/universe.py`'s `DEFAULT_UNIVERSE` reviewed — every
      symbol in it is one you are willing to hold.

## 2. Credentials & connectivity

- [ ] `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` are real **live**-account
      keys, not paper keys.
- [ ] Live connectivity verified *without* risking an accidental live
      order: set `TRADING_MODE=LIVE` and start the bot, but **do not**
      type the confirmation phrase. Confirm the banner
      (`app/startup.py`) shows your real account ID, equity, and buying
      power — that alone proves the live credentials and connection
      work. Then decline (type anything else) to abort cleanly.
- [ ] `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` configured, and at least
      one real alert has actually arrived in Telegram (e.g. by
      temporarily lowering `HEARTBEAT_STALE_SECONDS` and letting it
      fire) — not just verified against the test suite's fakes.
- [ ] `DATABASE_URL` points to a real, persistent file path, not
      `:memory:` and not a path that gets wiped on restart.

## 3. Extended paper-trading track record (this is what Stage 11 was for)

- [ ] The bot has run in PAPER mode continuously through at least one
      full monthly rebalance cycle — ideally several — without needing
      manual intervention.
- [ ] The dashboard's order history for the paper period has been
      reviewed: every submitted order resolved to a sane terminal state
      (filled/rejected/canceled). Nothing stuck open indefinitely.
- [ ] At least one startup reconciliation report from a *real* restart
      during the paper period has been reviewed — confirms reconciliation
      behaves as expected outside of tests, against your real paper
      account's actual state.
- [ ] At least one heartbeat-stale alert and recovery has been observed
      (even if deliberately triggered) — proves the alert pipeline works
      end to end, not only in the test suite.
- [ ] At least one deliberate crash/restart of the process during paper
      trading, confirming your process supervisor (NSSM or otherwise)
      actually restarts it, and that reconciliation runs cleanly
      afterward.

## 4. Operational readiness

- [ ] NSSM (or your chosen supervisor) is configured for auto-start and
      auto-restart *on this specific machine*, and you have tested it by
      actually killing the process and watching it come back.
- [ ] The dashboard (`app/web/main.py`) is running and reachable from
      wherever you will actually check it.
- [ ] You can read every dashboard panel — system status/heartbeat,
      account, positions, orders, risk limits, strategy parameters —
      and know what "STALE" vs "ACTIVE"/"ALIVE" means for each.
- [ ] You have a plan for who watches Telegram alerts and how quickly,
      especially for `CRITICAL` severity.

## 5. Safety mechanisms verified, not just trusted

- [ ] You have personally seen the LIVE-mode confirmation banner show
      correct, real account/equity/risk numbers (see section 2) before
      ever typing the confirmation phrase for real.
- [ ] You understand that typing anything other than the exact phrase
      `ENABLE LIVE TRADING` aborts startup — no partial credit, no retry
      prompt.
- [ ] You understand the Risk Engine (`app/risk/engine.py`) can and will
      veto or clip trades, with no override — including trades that
      might look "obviously right" in the moment. That is not a bug to
      route around; it is the one rule this entire project was built to
      never break.
- [ ] You have reviewed and are comfortable with the anti-martingale
      rule, correlation limits, and drawdown kill switch exactly as
      configured. They will halt or limit trading automatically and are
      not adjustable while the process is running.

## 6. Kill-switch / rollback procedure — decide this now, not during an incident

- [ ] You know how to stop the process cleanly (Ctrl+C locally, or an
      NSSM stop) and that **this does not cancel open orders**.
- [ ] You know how to check for and manually cancel open orders directly
      in Alpaca's own web dashboard/app. This codebase deliberately has
      no automated "cancel everything and go flat" function — it matches
      the project's conservative scope (see section 7) and its
      non-negotiable rule against any fund-transfer/withdrawal
      capability.
- [ ] You understand that switching `TRADING_MODE` back to `PAPER` does
      **not** close existing LIVE positions — positions live at the
      broker regardless of which mode this process is running in.
- [ ] You have decided, in advance, what would make you manually
      intervene (an alert you don't understand, an unexpected position,
      a drawdown approaching the kill-switch threshold) rather than
      waiting to see what happens.

## 7. What this system explicitly does not do

Read this before assuming otherwise:

- No withdrawal or fund-transfer capability, by design. Moving money in
  or out of the brokerage account is always a manual, out-of-band action.
- No martingale/doubling down; no leverage unless explicitly enabled.
- No ML-based or HFT strategy. This is a slower, rules-based
  trend/momentum system — it will not react to intraday news or
  volatility, by design.
- No handling of corporate actions beyond what Alpaca's own
  split/dividend-adjusted data already provides.
- No tax-lot optimization, no wash-sale awareness.
- No automatic "flatten everything" kill switch (see section 6) — the
  drawdown kill switch halts new buys, it does not sell existing
  positions for you.

## 8. Outside this codebase's scope — your own responsibility

- [ ] Confirmed you're legally permitted to run automated trading on this
      account, in your jurisdiction, and have reviewed Alpaca's own terms
      of service.
- [ ] Tax implications of this trading frequency/style understood, or
      referred to a professional.
- [ ] You are trading money you can genuinely afford to lose up to
      `MAX_DRAWDOWN_PCT` of — and ideally all of, since no system
      eliminates tail risk.
- [ ] Anyone who needs to know (family, business partner, accountant)
      knows this system exists and runs unattended.

## 9. Final go/no-go

- [ ] Every section above reviewed, not skimmed.
- [ ] You set `TRADING_MODE=LIVE` in `.env` yourself, deliberately.
- [ ] You will be present and watching for at least the first live
      rebalance cycle, not starting it and walking away.

---

Nothing above is enforced by code, and it can't be — that's the point.
The system's only mechanical safeguard is the one described in
`app/startup.py`: it will never switch itself into LIVE mode, and LIVE
mode will never proceed without the exact typed phrase. Everything else
on this page is judgment, and the judgment is yours.
