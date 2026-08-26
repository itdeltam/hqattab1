"""Market-hours handling via pandas_market_calendars. The backtest engine
never invents trading days from calendar dates -- it only ever iterates
sessions produced here, so weekends and exchange holidays are excluded the
same way for a backtest as they will be for the live scheduler (Stage 6)."""
from __future__ import annotations

import pandas as pd
import pandas_market_calendars as mcal


def trading_sessions(start: str, end: str, calendar: str = "NYSE") -> pd.DatetimeIndex:
    cal = mcal.get_calendar(calendar)
    schedule = cal.schedule(start_date=start, end_date=end)
    return schedule.index.normalize()


def monthly_rebalance_dates(sessions: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """First trading session of each calendar month present in `sessions`."""
    if len(sessions) == 0:
        return sessions
    by_month = pd.Series(sessions, index=sessions).groupby([sessions.year, sessions.month])
    return pd.DatetimeIndex(sorted(by_month.min().to_numpy()))
