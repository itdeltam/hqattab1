"""The backtest engine. Walks trading sessions one at a time and enforces
the Stage 2 no-look-ahead rule mechanically, not just by convention:
- A decision made "as of" a rebalance date reads signals computed through
  the *prior* session's close only.
- Orders implied by that decision execute at the rebalance date's *open*.
- End-of-day equity is marked at that same date's close -- which is
  bookkeeping (recording what happened), never an input to a decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from app.backtesting.costs import CommissionModel, FixedBpsSlippage, SlippageModel, ZeroCommission
from app.market_data.bars import PriceHistory
from app.strategy.params import StrategyParams
from app.strategy.rebalancing import compute_order_deltas, compute_target_weights
from app.strategy.signals import momentum_score, realized_vol, trend_filter


@dataclass(frozen=True)
class Trade:
    date: pd.Timestamp
    symbol: str
    side: str
    shares: float
    price: float
    commission: float


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: pd.Series
    trades: list[Trade]


@dataclass
class BacktestConfig:
    starting_capital: float = 100_000.0
    strategy_params: StrategyParams = field(default_factory=StrategyParams)
    commission_model: CommissionModel = field(default_factory=ZeroCommission)
    slippage_model: SlippageModel = field(default_factory=lambda: FixedBpsSlippage(bps=5.0))


class BacktestEngine:
    def __init__(self, config: BacktestConfig):
        self.config = config

    def run(self, history: PriceHistory, rebalance_dates: pd.DatetimeIndex) -> BacktestResult:
        params = self.config.strategy_params
        close = history.close
        open_ = history.open
        dates = history.dates
        rebalance_set = set(rebalance_dates)

        eligible_all = close.apply(lambda s: trend_filter(s, params))
        scores_all = close.apply(lambda s: momentum_score(s, params))
        vols_all = close.apply(lambda s: realized_vol(s, params.vol_window))

        cash = self.config.starting_capital
        shares = {symbol: 0.0 for symbol in history.symbols}
        momentum_holdings: set[str] = set()
        trades: list[Trade] = []
        equity_curve = pd.Series(index=dates, dtype=float)

        for i, date in enumerate(dates):
            if i > 0 and date in rebalance_set:
                prior_date = dates[i - 1]
                cash, shares, momentum_holdings = self._rebalance(
                    date=date,
                    prior_date=prior_date,
                    cash=cash,
                    shares=shares,
                    momentum_holdings=momentum_holdings,
                    eligible_prior=eligible_all.loc[prior_date],
                    scores_prior=scores_all.loc[prior_date],
                    vols_prior=vols_all.loc[prior_date],
                    reference_prices=close.loc[prior_date],
                    fill_prices=open_.loc[date],
                    params=params,
                    trades=trades,
                )

            equity_curve.iloc[i] = cash + sum(
                shares[symbol] * close.loc[date, symbol] for symbol in history.symbols
            )

        return BacktestResult(equity_curve=equity_curve, trades=trades)

    def _rebalance(
        self,
        date: pd.Timestamp,
        prior_date: pd.Timestamp,
        cash: float,
        shares: dict[str, float],
        momentum_holdings: set[str],
        eligible_prior: pd.Series,
        scores_prior: pd.Series,
        vols_prior: pd.Series,
        reference_prices: pd.Series,
        fill_prices: pd.Series,
        params: StrategyParams,
        trades: list[Trade],
    ) -> tuple[float, dict[str, float], set[str]]:
        weights, selected = compute_target_weights(eligible_prior, scores_prior, vols_prior, momentum_holdings, params)

        current_equity = cash + sum(
            shares[symbol] * reference_prices[symbol] for symbol in shares
        )

        deltas = compute_order_deltas(weights, shares, reference_prices, current_equity)

        for symbol, delta in deltas.items():
            fill_price_raw = fill_prices[symbol]
            if pd.isna(fill_price_raw):
                continue

            side = "buy" if delta > 0 else "sell"
            fill_price = self.config.slippage_model.fill_price(fill_price_raw, side)
            commission = self.config.commission_model.commission(abs(delta), fill_price)

            cash -= delta * fill_price
            cash -= commission
            shares[symbol] += delta

            trades.append(Trade(
                date=date, symbol=symbol, side=side,
                shares=abs(delta), price=fill_price, commission=commission,
            ))

        return cash, shares, selected
