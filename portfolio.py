"""
Portfolio analytics (pure functions, no I/O).

Kept separate from `store.py` (storage) and `app.py` (UI) so the maths can be
unit-tested without Streamlit or a network. Given a transaction ledger and a
price table, these reconstruct the portfolio through time.

Time-weighted return (TWR) is used for the vs-benchmark chart because it removes
the distorting effect of deposits/buys — it measures how your *choices* performed,
comparable to an index. (Prices are expected to be dividend-adjusted, so dividends
are already reflected and are NOT added again here.)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _snap(dates: pd.DatetimeIndex, d) -> pd.Timestamp | None:
    """First trading date on/after d (transactions may fall on weekends)."""
    later = dates[dates >= d]
    return later[0] if len(later) else None


def shares_over_time(tx: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Cumulative shares held per ticker on each date (BUY adds, SELL removes)."""
    tx = tx.copy()
    tx["date"] = pd.to_datetime(tx["date"])
    trade = tx[tx["type"].isin(["BUY", "SELL"])]
    tickers = sorted(trade["ticker"].unique())
    df = pd.DataFrame(0.0, index=dates, columns=tickers)
    for _, r in trade.iterrows():
        sign = 1.0 if r["type"] == "BUY" else -1.0
        df.loc[dates >= r["date"], r["ticker"]] += sign * r["quantity"]
    return df


def holdings_value(shares_df: pd.DataFrame, price_df: pd.DataFrame) -> pd.Series:
    """Market value of holdings on each date (same currency assumed across columns)."""
    aligned = price_df.reindex(index=shares_df.index,
                               columns=shares_df.columns).ffill()
    return (shares_df * aligned).sum(axis=1)


def external_flows(tx: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.Series:
    """Net capital added to holdings per day: +buys, -sells (at execution price)."""
    tx = tx.copy()
    tx["date"] = pd.to_datetime(tx["date"])
    f = pd.Series(0.0, index=dates)
    for _, r in tx.iterrows():
        if r["type"] not in ("BUY", "SELL"):
            continue
        d = _snap(dates, r["date"])
        if d is None:
            continue
        f.loc[d] += r["quantity"] * r["price"] * (1 if r["type"] == "BUY" else -1)
    return f


def twr_index(value: pd.Series, flow: pd.Series) -> pd.Series:
    """Chained time-weighted return index, starting at 1.0 on the first day the
    portfolio holds anything. Daily return neutralises same-day cash flows."""
    result = pd.Series(index=value.index, dtype=float)
    level, prev_v = 1.0, None
    for i in range(len(value)):
        v = float(value.iloc[i])
        fl = float(flow.iloc[i])
        if prev_v is None or prev_v <= 0:
            if v > 0:
                level = 1.0
                result.iloc[i] = level
                prev_v = v
            else:
                result.iloc[i] = np.nan
                prev_v = v
            continue
        ret = (v - prev_v - fl) / prev_v
        level *= (1 + ret)
        result.iloc[i] = level
        prev_v = v
    return result
