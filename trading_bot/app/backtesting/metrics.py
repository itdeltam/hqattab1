"""Performance statistics computed from a backtest's equity curve."""
from __future__ import annotations

import numpy as np
import pandas as pd


def total_return(equity_curve: pd.Series) -> float:
    return equity_curve.iloc[-1] / equity_curve.iloc[0] - 1


def cagr(equity_curve: pd.Series, periods_per_year: int = 252) -> float:
    n_periods = len(equity_curve) - 1
    if n_periods <= 0:
        return 0.0
    growth = equity_curve.iloc[-1] / equity_curve.iloc[0]
    years = n_periods / periods_per_year
    return growth ** (1 / years) - 1


def max_drawdown(equity_curve: pd.Series) -> float:
    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1
    return drawdown.min()


def annualized_vol(equity_curve: pd.Series, periods_per_year: int = 252) -> float:
    daily_returns = equity_curve.pct_change().dropna()
    return daily_returns.std() * np.sqrt(periods_per_year)


def sharpe_ratio(equity_curve: pd.Series, risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    daily_returns = equity_curve.pct_change().dropna()
    excess = daily_returns - risk_free_rate / periods_per_year
    vol = excess.std()
    if vol == 0:
        return 0.0
    return (excess.mean() / vol) * np.sqrt(periods_per_year)
