"""
Broker-CSV import (pure, testable).

Brokers all export different column names and use local-language action words, so
the app lets the user map columns, and this module normalises the result into the
transaction schema the ledger expects. No I/O here — the UI reads the file and
inserts the rows.
"""

from __future__ import annotations

import pandas as pd

VALID_TYPES = ["BUY", "SELL", "DIV", "DEPOSIT", "WITHDRAW"]

# Common Nordic broker action words → our types (extend as needed).
DEFAULT_TYPE_MAP = {
    "KJØP": "BUY", "KJØPT": "BUY", "KJOP": "BUY", "BUY": "BUY", "KÖP": "BUY",
    "SALG": "SELL", "SOLGT": "SELL", "SELL": "SELL", "SÄLJ": "SELL",
    "UTBYTTE": "DIV", "DIVIDEND": "DIV", "UTDELNING": "DIV",
    "INNSKUDD": "DEPOSIT", "DEPOSIT": "DEPOSIT", "INSÄTTNING": "DEPOSIT",
    "UTTAK": "WITHDRAW", "WITHDRAWAL": "WITHDRAW", "UTTAG": "WITHDRAW",
}


def normalize_transactions(df: pd.DataFrame, mapping: dict,
                           type_map: dict | None = None,
                           default_fee: float = 0.0) -> pd.DataFrame:
    """Turn a raw broker DataFrame into rows of
    (date, ticker, type, quantity, price, fee).

    mapping: {'date','ticker','type','quantity','price', optional 'fee'} → source column.
    type_map: extra action-word overrides merged on top of DEFAULT_TYPE_MAP.
    Rows whose type isn't recognised are dropped.
    """
    tmap = {**DEFAULT_TYPE_MAP, **{k.upper(): v for k, v in (type_map or {}).items()}}
    out = pd.DataFrame()
    out["date"] = pd.to_datetime(df[mapping["date"]], errors="coerce").dt.date.astype(str)
    out["ticker"] = df[mapping["ticker"]].astype(str).str.upper().str.strip()
    raw_type = df[mapping["type"]].astype(str).str.upper().str.strip()
    out["type"] = raw_type.map(lambda x: tmap.get(x, x))
    out["quantity"] = pd.to_numeric(df[mapping["quantity"]], errors="coerce").fillna(0.0).abs()
    out["price"] = pd.to_numeric(df[mapping["price"]], errors="coerce").fillna(0.0).abs()
    if mapping.get("fee"):
        out["fee"] = pd.to_numeric(df[mapping["fee"]], errors="coerce").fillna(0.0).abs()
    else:
        out["fee"] = default_fee
    out = out[out["type"].isin(VALID_TYPES)].reset_index(drop=True)
    return out
