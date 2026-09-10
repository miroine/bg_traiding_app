"""
Advanced analytics (pure functions, no I/O) — Phase 3.

Everything here takes prices/returns in and gives numbers/arrays out, so it can be
unit-tested without Streamlit or a network. The UI in app.py just feeds these
functions data from the provider and draws the results.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def sma(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window).mean()


def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    d = s.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# --------------------------------------------------------------------------- #
# Backtesting: lump sum + dollar-cost-averaging + optional rebalancing
# --------------------------------------------------------------------------- #
def _rebalance_key(d: pd.Timestamp, freq: str):
    if freq == "monthly":
        return (d.year, d.month)
    if freq == "quarterly":
        return (d.year, (d.month - 1) // 3)
    if freq == "annual":
        return d.year
    return None


def dca_backtest(price_df: pd.DataFrame, weights: dict, initial: float = 0.0,
                 monthly: float = 0.0, rebalance: str = "none"):
    """Simulate investing `initial` up front plus `monthly` every month, split by
    target weights, optionally rebalancing back to those weights.

    Returns (value_series, invested_series, cashflows) where cashflows is a list of
    (date, amount) with contributions negative and the final value positive — ready
    for xirr().
    """
    price_df = price_df.dropna()
    tickers = list(price_df.columns)
    w = np.array([weights.get(t, 0.0) for t in tickers], dtype=float)
    if w.sum() == 0:
        w = np.ones(len(tickers))
    w = w / w.sum()

    dates = price_df.index
    units = np.zeros(len(tickers))
    invested = 0.0
    values, invested_curve, cashflows = [], [], []
    month_key, reb_key = None, None

    for i, d in enumerate(dates):
        px = price_df.iloc[i].values.astype(float)
        if i == 0 and initial > 0:
            units += (initial * w) / px
            invested += initial
            cashflows.append((d, -initial))
        mk = (d.year, d.month)
        if monthly > 0 and mk != month_key:
            units += (monthly * w) / px
            invested += monthly
            cashflows.append((d, -monthly))
        month_key = mk

        rk = _rebalance_key(d, rebalance)
        if rebalance != "none" and i > 0 and rk != reb_key:
            val = float((units * px).sum())
            if val > 0:
                units = (val * w) / px
        reb_key = rk

        values.append(float((units * px).sum()))
        invested_curve.append(invested)

    value_s = pd.Series(values, index=dates)
    inv_s = pd.Series(invested_curve, index=dates)
    if len(value_s):
        cashflows.append((dates[-1], float(value_s.iloc[-1])))
    return value_s, inv_s, cashflows


def xirr(cashflows: list, lo: float = -0.9999, hi: float = 10.0) -> float:
    """Annualised money-weighted return (IRR for irregular dates) via bisection.
    cashflows: list of (date, amount), outflows negative, final value positive."""
    if len(cashflows) < 2:
        return float("nan")
    dates = [pd.Timestamp(d) for d, _ in cashflows]
    amts = [float(a) for _, a in cashflows]
    t0 = min(dates)
    yrs = [(d - t0).days / 365.25 for d in dates]

    def npv(r):
        return sum(a / (1 + r) ** y for a, y in zip(amts, yrs))

    flo, fhi = npv(lo), npv(hi)
    if np.isnan(flo) or np.isnan(fhi) or flo * fhi > 0:
        return float("nan")
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = npv(mid)
        if abs(fm) < 1e-7:
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


# --------------------------------------------------------------------------- #
# Risk & relationship
# --------------------------------------------------------------------------- #
def daily_returns(price_df: pd.DataFrame) -> pd.DataFrame:
    return price_df.pct_change().dropna(how="all")


def correlation_matrix(price_df: pd.DataFrame) -> pd.DataFrame:
    return daily_returns(price_df).corr()


def beta(asset_ret: pd.Series, market_ret: pd.Series) -> float:
    df = pd.concat([asset_ret, market_ret], axis=1).dropna()
    if len(df) < 3:
        return float("nan")
    cov = np.cov(df.iloc[:, 0], df.iloc[:, 1])
    return float(cov[0, 1] / cov[1, 1]) if cov[1, 1] else float("nan")


def risk_metrics(ret: pd.Series, rf: float = 0.0) -> dict:
    """Annualised risk stats from a daily-return series."""
    r = pd.Series(ret).dropna()
    if len(r) < 5:
        return {}
    vol = r.std() * np.sqrt(TRADING_DAYS)
    downside = r[r < 0]
    dd = downside.std() * np.sqrt(TRADING_DAYS) if len(downside) else 0.0
    mean_ann = r.mean() * TRADING_DAYS
    sharpe = (mean_ann - rf) / vol if vol > 0 else float("nan")
    sortino = (mean_ann - rf) / dd if dd > 0 else float("nan")
    var95 = np.percentile(r, 5)
    cvar95 = r[r <= var95].mean()
    cum = (1 + r).cumprod()
    mdd = ((cum - cum.cummax()) / cum.cummax()).min()
    return {
        "vol": vol * 100, "downside_dev": dd * 100,
        "sharpe": sharpe, "sortino": sortino,
        "var95_daily": var95 * 100, "cvar95_daily": cvar95 * 100,
        "max_dd": mdd * 100,
    }


# --------------------------------------------------------------------------- #
# Monte Carlo projection
# --------------------------------------------------------------------------- #
def monte_carlo(ret: pd.Series, start_value: float, days: int = TRADING_DAYS,
                n: int = 1000, seed: int = 0):
    """Parametric MC on daily returns. Returns (percentile_bands, end_values).
    percentile_bands: dict {p: array of length days+1} for a fan chart."""
    r = pd.Series(ret).dropna()
    mu, sd = float(r.mean()), float(r.std())
    rng = np.random.default_rng(seed)
    shocks = rng.normal(mu, sd, size=(n, days))
    paths = start_value * np.cumprod(1 + shocks, axis=1)
    paths = np.hstack([np.full((n, 1), start_value), paths])
    bands = {p: np.percentile(paths, p, axis=0) for p in (5, 25, 50, 75, 95)}
    return bands, paths[:, -1]


def efficient_frontier(price_df: pd.DataFrame, n: int = 3000, rf: float = 0.0,
                       seed: int = 0):
    """Long-only frontier by sampling random weight vectors (Dirichlet). Returns
    (cloud_df, highlights) where cloud_df has columns ret/vol/sharpe (annualised)
    and highlights marks the max-Sharpe and min-volatility portfolios with weights."""
    rets = price_df.pct_change().dropna()
    tickers = list(price_df.columns)
    mean = rets.mean().values * TRADING_DAYS
    cov = rets.cov().values * TRADING_DAYS
    k = len(tickers)
    rng = np.random.default_rng(seed)
    W = rng.dirichlet(np.ones(k), size=n)          # each row sums to 1, all >= 0
    port_ret = W @ mean
    port_vol = np.sqrt(np.einsum("ij,jk,ik->i", W, cov, W))
    with np.errstate(divide="ignore", invalid="ignore"):
        sharpe = (port_ret - rf) / np.where(port_vol > 0, port_vol, np.nan)
    cloud = pd.DataFrame({"ret": port_ret * 100, "vol": port_vol * 100, "sharpe": sharpe})
    imax = int(np.nanargmax(sharpe))
    imin = int(np.argmin(port_vol))

    def pack(i):
        return {"weights": dict(zip(tickers, W[i].round(4))),
                "ret": port_ret[i] * 100, "vol": port_vol[i] * 100,
                "sharpe": float(sharpe[i])}

    return cloud, {"max_sharpe": pack(imax), "min_vol": pack(imin)}
