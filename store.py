"""
Transaction store (SQLite).

Why this exists: the current app stores a static list of holdings in JSON. That
can't represent selling, dividends, fees, or realised profit — and almost every
portfolio feature you'll want depends on those. The fix is to store *transactions*
(an append-only ledger) and DERIVE positions from them. Never edit history; just
add a SELL.

Positions use the average-cost method (simple and common). If you later need tax
-accurate FIFO lots, that's a localized change in `compute_positions`.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pandas as pd

# Configurable so production can point at a persistent volume, e.g.
#   PORTFOLIO_DB=/data/portfolio.db streamlit run app.py
DB_PATH = Path(os.environ.get("PORTFOLIO_DB", "portfolio.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    date      TEXT    NOT NULL,           -- ISO date
    ticker    TEXT    NOT NULL,
    type      TEXT    NOT NULL,           -- BUY | SELL | DIV | DEPOSIT | WITHDRAW
    quantity  REAL    NOT NULL DEFAULT 0, -- shares (0 for DIV/DEPOSIT/WITHDRAW)
    price     REAL    NOT NULL DEFAULT 0, -- per-share price, or cash amount
    fee       REAL    NOT NULL DEFAULT 0,
    currency  TEXT    NOT NULL DEFAULT 'NOK',
    note      TEXT,
    portfolio TEXT    NOT NULL DEFAULT 'Main'
);
CREATE TABLE IF NOT EXISTS notes (
    ticker   TEXT PRIMARY KEY,
    thesis   TEXT,
    updated  TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker   TEXT NOT NULL,
    kind     TEXT NOT NULL,               -- price_above|price_below|rsi_above|rsi_below
    value    REAL NOT NULL,
    created  TEXT,
    notified INTEGER NOT NULL DEFAULT 0   -- 1 once delivered; cleared when condition clears
);
CREATE TABLE IF NOT EXISTS watchlist (
    ticker TEXT PRIMARY KEY,
    name   TEXT
);
"""


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.executescript(SCHEMA)
    # migrate pre-existing transactions tables that lack the portfolio column
    cols = [r[1] for r in c.execute("PRAGMA table_info(transactions)").fetchall()]
    if "portfolio" not in cols:
        c.execute("ALTER TABLE transactions ADD COLUMN portfolio TEXT NOT NULL DEFAULT 'Main'")
    acols = [r[1] for r in c.execute("PRAGMA table_info(alerts)").fetchall()]
    if acols and "notified" not in acols:
        c.execute("ALTER TABLE alerts ADD COLUMN notified INTEGER NOT NULL DEFAULT 0")
    return c


def add_transaction(date, ticker, ttype, quantity=0.0, price=0.0,
                    fee=0.0, currency="NOK", note="", portfolio="Main"):
    with _conn() as c:
        c.execute(
            "INSERT INTO transactions "
            "(date,ticker,type,quantity,price,fee,currency,note,portfolio) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (str(date), ticker.upper(), ttype.upper(),
             float(quantity), float(price), float(fee), currency, note, portfolio),
        )


def get_transactions(portfolio: str | None = None) -> pd.DataFrame:
    with _conn() as c:
        if portfolio:
            return pd.read_sql_query(
                "SELECT * FROM transactions WHERE portfolio = ? ORDER BY date, id",
                c, params=(portfolio,))
        return pd.read_sql_query(
            "SELECT * FROM transactions ORDER BY date, id", c)


def list_portfolios() -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT DISTINCT portfolio FROM transactions ORDER BY portfolio").fetchall()
    names = [r[0] for r in rows]
    return names or ["Main"]


def delete_transaction(tx_id: int):
    with _conn() as c:
        c.execute("DELETE FROM transactions WHERE id = ?", (int(tx_id),))


def compute_positions(tx: pd.DataFrame | None = None) -> pd.DataFrame:
    """Derive current holdings + realised P/L from the ledger (average cost)."""
    if tx is None:
        tx = get_transactions()
    cols = ["ticker", "shares", "avg_cost", "realised", "dividends"]
    if tx.empty:
        return pd.DataFrame(columns=cols)

    book: dict[str, dict] = {}
    for _, r in tx.iterrows():
        if r.type not in ("BUY", "SELL", "DIV"):
            continue  # DEPOSIT / WITHDRAW affect cash only, not positions
        b = book.setdefault(
            r.ticker, {"shares": 0.0, "cost": 0.0, "realised": 0.0, "div": 0.0})
        if r.type == "BUY":
            b["shares"] += r.quantity
            b["cost"] += r.quantity * r.price + r.fee
        elif r.type == "SELL":
            if b["shares"] > 0:
                avg = b["cost"] / b["shares"]
                b["realised"] += r.quantity * (r.price - avg) - r.fee
                b["cost"] -= r.quantity * avg
                b["shares"] -= r.quantity
        elif r.type == "DIV":
            b["div"] += r.price  # total cash dividend

    rows = []
    for tk, b in book.items():
        avg = b["cost"] / b["shares"] if b["shares"] > 1e-9 else 0.0
        rows.append({"ticker": tk, "shares": round(b["shares"], 6),
                     "avg_cost": avg, "realised": b["realised"],
                     "dividends": b["div"]})
    return pd.DataFrame(rows)


def compute_cash(tx: pd.DataFrame | None = None) -> float:
    """Cash balance implied by the ledger. Buys/fees drain it; sells, dividends
    and deposits add to it; withdrawals remove it."""
    if tx is None:
        tx = get_transactions()
    cash = 0.0
    for _, r in tx.iterrows():
        if r.type == "BUY":
            cash -= r.quantity * r.price + r.fee
        elif r.type == "SELL":
            cash += r.quantity * r.price - r.fee
        elif r.type == "DIV":
            cash += r.price
        elif r.type == "DEPOSIT":
            cash += r.price
        elif r.type == "WITHDRAW":
            cash -= r.price
    return cash


def net_deposits(tx: pd.DataFrame | None = None) -> float:
    """External capital put in (deposits minus withdrawals) — the denominator for
    a simple money-in vs value-now return."""
    if tx is None:
        tx = get_transactions()
    dep = tx.loc[tx.type == "DEPOSIT", "price"].sum()
    wd = tx.loc[tx.type == "WITHDRAW", "price"].sum()
    return float(dep - wd)


def get_note(ticker: str) -> str:
    with _conn() as c:
        row = c.execute("SELECT thesis FROM notes WHERE ticker = ?",
                        (ticker.upper(),)).fetchone()
    return row[0] if row and row[0] else ""


def set_note(ticker: str, thesis: str) -> None:
    from datetime import datetime
    with _conn() as c:
        c.execute(
            "INSERT INTO notes (ticker, thesis, updated) VALUES (?,?,?) "
            "ON CONFLICT(ticker) DO UPDATE SET thesis=excluded.thesis, "
            "updated=excluded.updated",
            (ticker.upper(), thesis, datetime.now().isoformat(timespec="seconds")))


def add_alert(ticker: str, kind: str, value: float) -> None:
    from datetime import datetime
    with _conn() as c:
        c.execute("INSERT INTO alerts (ticker, kind, value, created) VALUES (?,?,?,?)",
                  (ticker.upper(), kind, float(value),
                   datetime.now().isoformat(timespec="seconds")))


def list_alerts() -> pd.DataFrame:
    with _conn() as c:
        return pd.read_sql_query("SELECT * FROM alerts ORDER BY id", c)


def delete_alert(alert_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM alerts WHERE id = ?", (int(alert_id),))


def set_alert_notified(alert_id: int, notified: bool) -> None:
    with _conn() as c:
        c.execute("UPDATE alerts SET notified = ? WHERE id = ?",
                  (1 if notified else 0, int(alert_id)))


# --- Watchlist (user-editable universe; seeded once from defaults) ------------
def seed_watchlist(default: dict) -> None:
    with _conn() as c:
        n = c.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
        if n == 0 and default:
            c.executemany("INSERT OR IGNORE INTO watchlist (ticker, name) VALUES (?,?)",
                          [(k.upper(), v) for k, v in default.items()])


def get_watchlist() -> dict:
    with _conn() as c:
        rows = c.execute("SELECT ticker, name FROM watchlist ORDER BY rowid").fetchall()
    return {t: (n or t) for t, n in rows}


def add_watchlist(ticker: str, name: str = "") -> None:
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO watchlist (ticker, name) VALUES (?,?)",
                  (ticker.upper(), name or ticker.upper()))


def remove_watchlist(ticker: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker.upper(),))


if __name__ == "__main__":
    # tiny self-test with an in-effect throwaway db
    DB_PATH = Path("._selftest.db")
    if DB_PATH.exists():
        DB_PATH.unlink()
    add_transaction("2024-01-02", "EQNR.OL", "BUY", 100, 300, fee=29)
    add_transaction("2024-06-01", "EQNR.OL", "BUY", 50, 280, fee=29)
    add_transaction("2024-09-01", "EQNR.OL", "SELL", 60, 330, fee=29)
    add_transaction("2024-08-15", "EQNR.OL", "DIV", price=1200)
    print(compute_positions().to_string(index=False))
    DB_PATH.unlink()
