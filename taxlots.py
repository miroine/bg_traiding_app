"""
FIFO tax-lot accounting (pure, testable).

The Portfolio tab's default realised P/L uses average cost, which is simple and fine
for tracking performance. For tax, Norway (like many jurisdictions) disposes of shares
first-in-first-out, so realised gains depend on *which* lots you sold. This module
reconstructs individual lots and matches each sale against the oldest open lots.

`fifo_positions` returns the same columns as store.compute_positions
(ticker, shares, avg_cost, realised, dividends) so the app can swap methods freely.
`fifo_realised` returns a per-disposal tax report with acquisition/disposal dates and
holding period.

This is bookkeeping, not tax advice — rules on shielding deductions, fees and currency
vary, so confirm with a tax adviser before filing.
"""

from __future__ import annotations

from collections import deque, defaultdict

import pandas as pd

_POS_COLS = ["ticker", "shares", "avg_cost", "realised", "dividends"]
_REAL_COLS = ["ticker", "acquired", "disposed", "shares", "cost", "proceeds",
              "gain", "holding_days"]
_LOT_COLS = ["ticker", "acquired", "shares", "price_per_share", "cost"]


def _process(tx: pd.DataFrame):
    if tx.empty:
        return {}, [], defaultdict(float)
    tx = tx.copy()
    tx["_d"] = pd.to_datetime(tx["date"])
    tx = tx.sort_values(["_d", "id"]) if "id" in tx.columns else tx.sort_values("_d")

    lots: dict[str, deque] = defaultdict(deque)
    realised: list[dict] = []
    dividends: dict[str, float] = defaultdict(float)

    for _, r in tx.iterrows():
        tk, typ = r["ticker"], r["type"]
        qty, price, fee = float(r["quantity"]), float(r["price"]), float(r["fee"])
        if typ == "BUY" and qty > 0:
            cost = qty * price + fee
            lots[tk].append({"date": r["_d"], "shares": qty, "pps": cost / qty})
        elif typ == "SELL" and qty > 0:
            net_pps = (qty * price - fee) / qty  # sale fee spread across sold shares
            remaining = qty
            while remaining > 1e-9 and lots[tk]:
                lot = lots[tk][0]
                take = min(remaining, lot["shares"])
                realised.append({
                    "ticker": tk, "acquired": lot["date"], "disposed": r["_d"],
                    "shares": take, "cost": take * lot["pps"],
                    "proceeds": take * net_pps, "gain": take * (net_pps - lot["pps"]),
                    "holding_days": int((r["_d"] - lot["date"]).days)})
                lot["shares"] -= take
                remaining -= take
                if lot["shares"] <= 1e-9:
                    lots[tk].popleft()
        elif typ == "DIV":
            dividends[tk] += price
    return lots, realised, dividends


def fifo_realised(tx: pd.DataFrame) -> pd.DataFrame:
    """Per-disposal realised gains, FIFO-matched, with holding period (tax report)."""
    _, realised, _ = _process(tx)
    if not realised:
        return pd.DataFrame(columns=_REAL_COLS)
    df = pd.DataFrame(realised)
    df["acquired"] = pd.to_datetime(df["acquired"]).dt.date.astype(str)
    df["disposed"] = pd.to_datetime(df["disposed"]).dt.date.astype(str)
    return df[_REAL_COLS]


def open_lots(tx: pd.DataFrame) -> pd.DataFrame:
    """Remaining un-sold lots with their original acquisition dates and cost."""
    lots, _, _ = _process(tx)
    rows = []
    for tk, dq in lots.items():
        for lot in dq:
            rows.append({"ticker": tk,
                         "acquired": pd.to_datetime(lot["date"]).date().isoformat(),
                         "shares": lot["shares"], "price_per_share": lot["pps"],
                         "cost": lot["shares"] * lot["pps"]})
    return pd.DataFrame(rows, columns=_LOT_COLS)


def fifo_positions(tx: pd.DataFrame) -> pd.DataFrame:
    """Aggregated positions with FIFO realised P/L — same shape as
    store.compute_positions, so it can be used interchangeably in the UI."""
    lots, realised, dividends = _process(tx)
    real_by_tk: dict[str, float] = defaultdict(float)
    for row in realised:
        real_by_tk[row["ticker"]] += row["gain"]

    tickers = set(lots) | set(real_by_tk) | set(dividends)
    rows = []
    for tk in tickers:
        shares = sum(lot["shares"] for lot in lots.get(tk, []))
        cost = sum(lot["shares"] * lot["pps"] for lot in lots.get(tk, []))
        avg = cost / shares if shares > 1e-9 else 0.0
        rows.append({"ticker": tk, "shares": round(shares, 6), "avg_cost": avg,
                     "realised": real_by_tk.get(tk, 0.0),
                     "dividends": dividends.get(tk, 0.0)})
    return pd.DataFrame(rows, columns=_POS_COLS)
