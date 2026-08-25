import pandas as pd

from app.backtesting.calendar import monthly_rebalance_dates, trading_sessions


def test_trading_sessions_excludes_weekends_and_holidays():
    sessions = trading_sessions("2022-01-01", "2022-12-31")
    weekdays = pd.bdate_range("2022-01-01", "2022-12-31")

    # NYSE holidays (New Year's, MLK, Presidents, Good Friday, Memorial,
    # Juneteenth, July 4th, Labor Day, Thanksgiving, Christmas, ...) fall on
    # weekdays most years, so there must be strictly fewer sessions than
    # weekdays -- if this ever fails equal, holiday exclusion silently broke.
    assert len(sessions) < len(weekdays)
    assert sessions.is_monotonic_increasing
    assert sessions.is_unique


def test_trading_sessions_excludes_known_holiday():
    # July 4th, 2022 fell on a Monday -- Independence Day, NYSE closed.
    sessions = trading_sessions("2022-07-01", "2022-07-08")
    assert pd.Timestamp("2022-07-04") not in sessions
    assert pd.Timestamp("2022-07-05") in sessions


def test_monthly_rebalance_dates_one_per_month():
    sessions = trading_sessions("2022-01-01", "2022-12-31")
    rebalances = monthly_rebalance_dates(sessions)

    assert len(rebalances) == 12
    for r in rebalances:
        assert r in sessions  # every rebalance date must be an actual trading session


def test_monthly_rebalance_dates_is_first_session_of_month():
    sessions = trading_sessions("2022-01-01", "2022-01-31")
    rebalances = monthly_rebalance_dates(sessions)

    assert len(rebalances) == 1
    assert rebalances[0] == sessions[0]


def test_monthly_rebalance_dates_empty_input():
    empty = pd.DatetimeIndex([])
    assert len(monthly_rebalance_dates(empty)) == 0
