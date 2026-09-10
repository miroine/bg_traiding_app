"""
Alert evaluation (pure, testable).

Shared by the Streamlit UI (checks on load) and alert_runner.py (checks on a cron
schedule). Keeping the condition logic here means both paths agree exactly.
"""

from __future__ import annotations

PRICE_KINDS = ("price_above", "price_below")
RSI_KINDS = ("rsi_above", "rsi_below")


def evaluate_condition(kind: str, value: float, price=None, rsi=None) -> bool:
    if kind == "price_above":
        return price is not None and price >= value
    if kind == "price_below":
        return price is not None and price <= value
    if kind == "rsi_above":
        return rsi is not None and rsi >= value
    if kind == "rsi_below":
        return rsi is not None and rsi <= value
    return False


def describe(row, current) -> str:
    metric = "price" if row["kind"].startswith("price") else "RSI"
    op = "≥" if row["kind"].endswith("above") else "≤"
    cur = f"{current:.2f}" if current is not None else "?"
    return f"{row['ticker']} {metric} {cur} {op} {row['value']:g}"


def evaluate_all(alerts_df, price_fn, rsi_fn) -> list:
    """Evaluate every alert. price_fn/rsi_fn are callables ticker->value (they may
    raise or return None; that's treated as 'no data'). Returns a list of dicts with
    id, ticker, kind, value, current, triggered."""
    results = []
    for _, row in alerts_df.iterrows():
        kind = row["kind"]
        price = rsi = None
        try:
            if kind in PRICE_KINDS:
                price = price_fn(row["ticker"])
            elif kind in RSI_KINDS:
                rsi = rsi_fn(row["ticker"])
        except Exception:
            pass
        current = price if kind in PRICE_KINDS else rsi
        results.append({
            "id": int(row["id"]), "ticker": row["ticker"], "kind": kind,
            "value": float(row["value"]), "current": current,
            "triggered": evaluate_condition(kind, float(row["value"]), price, rsi)})
    return results
