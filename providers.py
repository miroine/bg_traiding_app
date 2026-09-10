"""
Data-provider layer.

Why this exists: right now the app calls yfinance directly all over the place.
That makes it painful to (a) move to real-time/paid data later, or (b) add
fundamentals and news. This module hides *where* data comes from behind one
interface, so the rest of the app never imports yfinance again — it asks a
`PriceProvider` for what it needs.

To switch data sources later, write a new class (EODHDProvider, InfrontProvider…)
that implements the same three methods, and change ONE line where the app picks
its provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class PriceProvider(ABC):
    """The contract every data source must fulfil."""

    @abstractmethod
    def get_history(self, ticker: str, period: str = "1y",
                    interval: str = "1d") -> pd.DataFrame:
        """OHLCV DataFrame indexed by date."""

    @abstractmethod
    def get_quote(self, ticker: str) -> dict:
        """Latest snapshot: {'price', 'prev_close', 'volume', 'currency'}."""

    @abstractmethod
    def get_fundamentals(self, ticker: str) -> dict:
        """Valuation basics: {'pe', 'dividend_yield', 'market_cap', 'name', ...}."""

    def get_quotes(self, tickers) -> dict:
        """Batch snapshot: {ticker: quote_dict}. Default loops get_quote;
        providers can override with a single efficient call (Yahoo does)."""
        return {t: self.get_quote(t) for t in tickers}

    def get_fx_rate(self, base: str, quote: str = "NOK") -> float:
        """1 unit of `base` in `quote` currency. Default: 1.0 if same, else NaN.
        Providers override to supply real rates."""
        return 1.0 if base == quote else float("nan")

    def get_news(self, ticker: str, limit: int = 6) -> list:
        """Recent headlines: list of {title, link, publisher}. Default: none."""
        return []


class YahooProvider(PriceProvider):
    """Free, ~15-min delayed data via yfinance. Good default for a personal app."""

    def __init__(self):
        import yfinance as yf  # imported lazily so swapping providers drops the dep
        self._yf = yf

    def get_history(self, ticker, period="1y", interval="1d"):
        df = self._yf.Ticker(ticker).history(
            period=period, interval=interval, auto_adjust=True)
        return df.dropna(how="all")

    def get_quote(self, ticker):
        try:
            fi = self._yf.Ticker(ticker).fast_info
            return {
                "price": float(fi.last_price),
                "prev_close": float(fi.previous_close),
                "volume": float(getattr(fi, "last_volume", float("nan"))),
                "currency": getattr(fi, "currency", "NOK"),
            }
        except Exception:
            h = self.get_history(ticker, period="5d")
            closes = h["Close"].dropna()
            return {
                "price": float(closes.iloc[-1]),
                "prev_close": float(closes.iloc[-2]),
                "volume": float(h["Volume"].dropna().iloc[-1]),
                "currency": "NOK",
            }

    def get_quotes(self, tickers):
        tickers = list(tickers)
        if not tickers:
            return {}
        data = self._yf.download(
            tickers, period="5d", interval="1d", group_by="ticker",
            progress=False, threads=True, auto_adjust=True)
        out = {}
        for t in tickers:
            try:
                sub = data[t] if len(tickers) > 1 else data
                closes = sub["Close"].dropna()
                out[t] = {
                    "price": float(closes.iloc[-1]),
                    "prev_close": float(closes.iloc[-2]),
                    "volume": float(sub["Volume"].dropna().iloc[-1]),
                    "currency": "NOK",
                }
            except Exception:
                out[t] = {"price": float("nan"), "prev_close": float("nan"),
                          "volume": float("nan"), "currency": "NOK"}
        return out

    def get_fx_rate(self, base, quote="NOK"):
        if base == quote:
            return 1.0
        try:
            h = self._yf.Ticker(f"{base}{quote}=X").history(period="5d")
            return float(h["Close"].dropna().iloc[-1])
        except Exception:
            return float("nan")

    def get_news(self, ticker, limit=6):
        try:
            raw = self._yf.Ticker(ticker).news or []
        except Exception:
            return []
        out = []
        for item in raw[:limit]:
            c = item.get("content", item)  # newer yfinance nests under 'content'
            title = c.get("title") or item.get("title")
            link = ((c.get("canonicalUrl") or {}).get("url")
                    or (c.get("clickThroughUrl") or {}).get("url")
                    or item.get("link"))
            pub = ((c.get("provider") or {}).get("displayName")
                   or item.get("publisher"))
            if title:
                out.append({"title": title, "link": link, "publisher": pub})
        return out

    def get_fundamentals(self, ticker):
        info = {}
        try:
            info = self._yf.Ticker(ticker).info or {}
        except Exception:
            pass
        return {
            "name": info.get("shortName") or info.get("longName") or ticker,
            "pe": info.get("trailingPE"),
            "dividend_yield": info.get("dividendYield"),
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector"),
            "currency": info.get("currency", "NOK"),
        }


def _period_to_from(period: str) -> str:
    from datetime import date, timedelta
    days = {"3mo": 92, "6mo": 183, "1y": 366, "2y": 731,
            "5y": 1827, "10y": 3653}.get(period)
    if days is None:
        return "1990-01-01"
    return (date.today() - timedelta(days=days)).isoformat()


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


class EODHDProvider(PriceProvider):
    """Paid / real-time data via EOD Historical Data (https://eodhd.com).

    Set EODHD_API_KEY in the environment, then run with DATA_PROVIDER=eodhd.
    Covers Oslo Børs (e.g. EQNR.OL). Uses only the standard library.

    NOTE: endpoint paths and JSON field names follow EODHD's docs at
    https://eodhd.com/financial-apis/ — verify them against the current docs, as
    vendor APIs change. Parsing here is defensive so a missing field degrades
    gracefully rather than crashing the app.
    """

    BASE = "https://eodhd.com/api"

    def __init__(self, api_key: str | None = None):
        import os
        self.key = api_key or os.environ.get("EODHD_API_KEY")
        if not self.key:
            raise RuntimeError(
                "EODHD_API_KEY is not set. Add it to your environment, or use the "
                "Yahoo provider (unset DATA_PROVIDER).")

    def _get(self, path: str, params: dict):
        import json
        import urllib.parse
        import urllib.request
        query = {**params, "api_token": self.key, "fmt": "json"}
        url = f"{self.BASE}/{path}?{urllib.parse.urlencode(query)}"
        with urllib.request.urlopen(url, timeout=20) as resp:
            return json.loads(resp.read().decode())

    def get_history(self, ticker, period="1y", interval="1d"):
        import pandas as pd
        data = self._get(f"eod/{ticker}",
                         {"period": "d", "from": _period_to_from(period)})
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        df["Date"] = pd.to_datetime(df["date"])
        df = df.set_index("Date").rename(columns={
            "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "adjusted_close": "AdjClose", "volume": "Volume"})
        if "AdjClose" in df:            # match Yahoo's auto_adjust (total return)
            df["Close"] = df["AdjClose"]
        keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df]
        return df[keep].astype(float)

    def get_quote(self, ticker):
        d = self._get(f"real-time/{ticker}", {})
        return {"price": _f(d.get("close")), "prev_close": _f(d.get("previousClose")),
                "volume": _f(d.get("volume")) or 0.0, "currency": "NOK"}

    # get_quotes falls back to the base-class loop (correct; verify a batch endpoint
    # in the docs if you want fewer round-trips).

    def get_fundamentals(self, ticker):
        try:
            d = self._get(f"fundamentals/{ticker}", {})
        except Exception:
            return {"name": ticker}
        g = d.get("General", {}) or {}
        h = d.get("Highlights", {}) or {}
        return {"name": g.get("Name") or ticker, "pe": _f(h.get("PERatio")),
                "dividend_yield": _f(h.get("DividendYield")),
                "market_cap": _f(h.get("MarketCapitalization")),
                "sector": g.get("Sector"), "currency": g.get("CurrencyCode", "NOK")}

    def get_fx_rate(self, base, quote="NOK"):
        if base == quote:
            return 1.0
        try:
            d = self._get(f"real-time/{base}{quote}.FOREX", {})
            return _f(d.get("close")) or float("nan")
        except Exception:
            return float("nan")

    def get_news(self, ticker, limit=6):
        try:
            data = self._get("news", {"s": ticker, "limit": limit}) or []
        except Exception:
            return []
        out = []
        for it in data[:limit]:
            title = it.get("title")
            if title:
                out.append({"title": title, "link": it.get("link"),
                            "publisher": (it.get("symbols") or [ticker])[0]})
        return out


# The app imports THIS. Pick the source with DATA_PROVIDER=yahoo|eodhd (default yahoo).
def get_provider() -> PriceProvider:
    import os
    name = os.environ.get("DATA_PROVIDER", "yahoo").lower()
    if name == "eodhd":
        return EODHDProvider()
    return YahooProvider()
