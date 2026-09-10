"""
Oslo Børs Trading Desk  —  Phases 0–4
-------------------------------------
Personal Streamlit app for the Norwegian market.

Phase 0: provider-backed data + transaction-ledger portfolio.
Phase 1: fundamentals, FX→NOK, data-freshness.
Phase 2: cash tracking + time-weighted portfolio-vs-OBX performance.
Phase 3: DCA/rebalance backtest, Monte Carlo, correlation & beta, risk metrics.
Phase 4: fundamentals screener, configurable signals, per-stock news (+ optional
         AI summary), and a saved thesis/checklist note per stock.

Run:
    pip install -r requirements.txt
    streamlit run app.py

Optional AI news summaries: `pip install anthropic` and set ANTHROPIC_API_KEY.

Data is delayed (~15 min via Yahoo). Not financial advice.
"""

import hmac
import os
from datetime import date, datetime

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import analytics as an
import alerts as alert_logic
import importers as imp
import notify
import portfolio as pf
import store
import taxlots
from providers import get_provider

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
st.set_page_config(page_title="Oslo Børs Trading Desk", page_icon="📈", layout="wide")
CURRENCY = "NOK"
INDEX_TICKER = "^OBX"
# API model for optional news summaries. See https://docs.claude.com/en/docs/about-claude/models
SUMMARY_MODEL = "claude-haiku-4-5-20251001"


# --------------------------------------------------------------------------- #
# Optional single-user password gate (Phase 5).
# Enable by setting APP_PASSWORD in the environment or `app_password` in secrets.
# If neither is set, the app is open (fine for local use).
# --------------------------------------------------------------------------- #
def require_auth():
    pw = os.environ.get("APP_PASSWORD")
    if not pw:
        try:
            pw = st.secrets.get("app_password")
        except Exception:
            pw = None
    if not pw:
        return
    if st.session_state.get("authed"):
        return
    st.markdown("## 🔒 Oslo Børs Trading Desk")
    entered = st.text_input("Password", type="password")
    if entered:
        if hmac.compare_digest(entered, str(pw)):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Incorrect password — try again.")
    st.stop()


require_auth()

# --------------------------------------------------------------------------- #
# Light visual polish. The main palette lives in .streamlit/config.toml; this
# just tightens spacing and gives the tab bar and header a calmer feel.
# --------------------------------------------------------------------------- #
st.markdown(
    """
    <style>
      .block-container {padding-top: 2.2rem; max-width: 1250px;}
      h1, h2, h3 {letter-spacing: -0.01em;}
      .app-header {display:flex; align-items:baseline; gap:.6rem; margin-bottom:.1rem;}
      .app-header .name {font-size:1.55rem; font-weight:700; color:#0B3B4A;}
      .app-header .dot {color:#0B6E7A; font-weight:700;}
      .app-sub {color:#5B6B7A; font-size:.9rem; margin:0 0 .8rem 0;}
      .stTabs [data-baseweb="tab-list"] {gap:.25rem;}
      .stTabs [data-baseweb="tab"] {padding:.4rem .8rem;}
      [data-testid="stMetricValue"] {font-size:1.5rem;}
    </style>
    <div class="app-header">
      <span class="name">Oslo Børs Trading Desk</span>
      <span class="dot">●</span>
    </div>
    <p class="app-sub">Follow the Norwegian market, track a real portfolio, simulate, and
    pressure-test your ideas — all in NOK. Delayed data · not financial advice.</p>
    """,
    unsafe_allow_html=True,
)

DEFAULT_UNIVERSE = {
    "EQNR.OL": "Equinor", "DNB.OL": "DNB Bank", "TEL.OL": "Telenor",
    "NHY.OL": "Norsk Hydro", "MOWI.OL": "Mowi", "YAR.OL": "Yara International",
    "AKRBP.OL": "Aker BP", "ORK.OL": "Orkla", "SALM.OL": "SalMar",
    "KOG.OL": "Kongsberg Gruppen", "STB.OL": "Storebrand", "SUBC.OL": "Subsea 7",
    "GJF.OL": "Gjensidige Forsikring", "FRO.OL": "Frontline", "TGS.OL": "TGS",
    "AKSO.OL": "Aker Solutions", "SCATC.OL": "Scatec", "BAKKA.OL": "Bakkafrost",
    "NAS.OL": "Norwegian Air Shuttle", "TOM.OL": "Tomra Systems",
}
# Seed once, then read the live (user-editable) watchlist. Falls back to defaults
# if the user ever empties it, so the tabs always have something to show.
store.seed_watchlist(DEFAULT_UNIVERSE)
OSLO_UNIVERSE = store.get_watchlist() or DEFAULT_UNIVERSE


# --------------------------------------------------------------------------- #
# Cached data access — the ONLY place the app talks to a data source
# --------------------------------------------------------------------------- #
@st.cache_resource
def provider():
    return get_provider()


@st.cache_data(ttl=300, show_spinner=False)
def hist(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    return provider().get_history(ticker, period, interval)


@st.cache_data(ttl=180, show_spinner=False)
def quotes(tickers: tuple) -> dict:
    return provider().get_quotes(list(tickers))


@st.cache_data(ttl=180, show_spinner=False)
def quote(ticker: str) -> dict:
    return provider().get_quote(ticker)


@st.cache_data(ttl=3600, show_spinner=False)
def fundamentals(ticker: str) -> dict:
    return provider().get_fundamentals(ticker)


@st.cache_data(ttl=1800, show_spinner=False)
def fx_rate(ccy: str) -> float:
    return provider().get_fx_rate(ccy, CURRENCY)


@st.cache_data(ttl=900, show_spinner=False)
def news(ticker: str) -> list:
    return provider().get_news(ticker)


@st.cache_data(ttl=180, show_spinner=False)
def data_as_of() -> datetime:
    return datetime.now()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def sma(s, w):
    return s.rolling(w).mean()


def rsi(s, period=14):
    d = s.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def max_drawdown(cum):
    peak = cum.cummax()
    return float(((cum - peak) / peak).min() * 100)


def money(x):
    return f"{x:,.0f} {CURRENCY}" if pd.notna(x) else "–"


def price_now(ticker):
    return quote(ticker).get("price", float("nan"))


def naive_index(idx):
    return pd.to_datetime(pd.DatetimeIndex(idx).date)


def big_number(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    for unit, div in [("T", 1e12), ("B", 1e9), ("M", 1e6)]:
        if abs(x) >= div:
            return f"{x/div:.1f}{unit}"
    return f"{x:,.0f}"


def period_for(first_dt):
    yrs = (date.today() - first_dt).days / 365.25
    return ("1y" if yrs <= 1 else "2y" if yrs <= 2 else
            "5y" if yrs <= 5 else "10y" if yrs <= 10 else "max")


def price_frame(tickers, period, to_nok=True):
    """Aligned NOK-converted close prices for a set of tickers."""
    cols = {}
    for t in tickers:
        s = hist(t, period=period)["Close"]
        if s.empty:
            continue
        rate = (fx_rate(quote(t).get("currency", "NOK")) or 1.0) if to_nok else 1.0
        cols[t] = s * rate
    df = pd.DataFrame(cols)
    if not df.empty:
        df.index = naive_index(df.index)
    return df.dropna(how="all")


def summarize_news(ticker, headlines):
    """Optional AI summary of headlines. Returns text or None if unavailable."""
    if not os.environ.get("ANTHROPIC_API_KEY") or not headlines:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic()
        joined = "\n".join(f"- {h['title']}" for h in headlines)
        msg = client.messages.create(
            model=SUMMARY_MODEL, max_tokens=300,
            messages=[{"role": "user", "content":
                       f"Summarise the current news picture for {ticker} in 3 short, "
                       f"neutral bullet points. No investment advice.\n\n{joined}"}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
st.sidebar.title("📈 Oslo Børs Trading Desk")
st.sidebar.caption("Personal market tracker & portfolio simulator")

# Active portfolio (Phase: multiple portfolios)
_ports = store.list_portfolios()
_choice = st.sidebar.selectbox("Portfolio", _ports + ["➕ New portfolio…"])
if _choice == "➕ New portfolio…":
    _new = st.sidebar.text_input("New portfolio name", placeholder="e.g. Long-term")
    active_portfolio = _new.strip() or "Main"
else:
    active_portfolio = _choice
st.sidebar.divider()

if st.sidebar.button("🔄 Refresh market data"):
    st.cache_data.clear()
    st.rerun()

with st.sidebar.expander("⭐ Manage watchlist"):
    nt = st.text_input("Add ticker", placeholder="e.g. NEL.OL", key="wl_add")
    if st.button("Add", key="wl_add_btn") and nt.strip():
        sym = nt.strip().upper()
        try:
            nm = fundamentals(sym).get("name") or sym
        except Exception:
            nm = sym
        store.add_watchlist(sym, nm)
        st.rerun()
    rem = st.selectbox("Remove", ["—"] + list(OSLO_UNIVERSE.keys()), key="wl_rm")
    if st.button("Remove", key="wl_rm_btn") and rem != "—":
        store.remove_watchlist(rem)
        st.rerun()
    st.caption("Use Oslo Børs tickers ending in `.OL`. Changes are saved.")
stamp = data_as_of()
age_min = (datetime.now() - stamp).total_seconds() / 60
st.sidebar.caption(f"🕒 Prices as of **{stamp:%H:%M}** (~{age_min:.0f} min ago)")
try:
    st.sidebar.caption(f"🔌 Data source: **{provider().__class__.__name__.replace('Provider','')}**")
except Exception:
    pass
st.sidebar.divider()
st.sidebar.caption("Data: Yahoo Finance (delayed ~15 min). Not financial advice. "
                   "Transactions stored locally in `portfolio.db`.")

(tab_market, tab_stock, tab_portfolio, tab_sim,
 tab_risk, tab_screener) = st.tabs(
    ["🌍 Market", "🔍 Stock", "💼 Portfolio", "🧪 Simulator", "📊 Risk", "🔎 Screener & signals"])

# --------------------------------------------------------------------------- #
# TAB 1 — Market
# --------------------------------------------------------------------------- #
with tab_market:
    st.subheader("Norwegian market overview")
    with st.expander("ℹ️ How to use this tab"):
        st.write("A live-ish snapshot of the Oslo Børs. The OBX index chart shows the "
                 "broad market's last six months; the watchlist ranks the tracked names "
                 "by today's move, with the biggest risers and fallers called out below. "
                 "Add or remove names by editing `OSLO_UNIVERSE` at the top of `app.py`.")

    # --- Price / RSI alerts (checked on load; run alert_runner.py for 24/7) ---
    alerts_df = store.list_alerts()
    if not alerts_df.empty:
        res = alert_logic.evaluate_all(
            alerts_df, price_fn=price_now,
            rsi_fn=lambda t: float(rsi(hist(t, "6mo")["Close"]).iloc[-1]))
        fired = [alert_logic.describe(r, r["current"]) for r in res if r["triggered"]]
        if fired:
            st.warning("🔔 **Alerts triggered:** " + "  ·  ".join(fired))

    with st.expander("🔔 Manage alerts"):
        st.caption("Checked when you open or refresh. For 24/7 monitoring, run "
                   "`alert_runner.py` on a schedule (see the README) — it delivers by "
                   "email or push even when the app is closed.")
        a1, a2, a3, a4 = st.columns([2, 2, 1, 1])
        atk = a1.selectbox("Ticker", list(OSLO_UNIVERSE.keys()),
                           format_func=lambda x: f"{OSLO_UNIVERSE.get(x, x)} ({x})", key="al_tk")
        akind = a2.selectbox("Condition",
                             ["price_above", "price_below", "rsi_above", "rsi_below"], key="al_kind")
        aval = a3.number_input("Value", min_value=0.0, value=0.0, step=1.0, key="al_val")
        if a4.button("Add", key="al_add"):
            store.add_alert(atk, akind, aval)
            st.rerun()
        for _, al in alerts_df.iterrows():
            cc = st.columns([5, 1])
            cc[0].write(f"#{int(al['id'])} · **{al['ticker']}** · "
                        f"{al['kind'].replace('_', ' ')} {al['value']:g}")
            if cc[1].button("Delete", key=f"del_al_{int(al['id'])}"):
                store.delete_alert(int(al["id"]))
                st.rerun()
        cfg = notify.channels_configured()
        if cfg:
            if st.button("Send test notification"):
                sent = notify.notify("Oslo Børs test",
                                     "Test alert from Oslo Børs Trading Desk.")
                st.success(f"Sent via {', '.join(sent)}." if sent
                           else "No channel accepted the message — check your settings.")
        else:
            st.caption("Set `NTFY_TOPIC` (push) or `SMTP_*` (email) to enable delivery.")

    idx = hist(INDEX_TICKER, period="6mo")
    if not idx.empty:
        last, prev = float(idx["Close"].iloc[-1]), float(idx["Close"].iloc[-2])
        c1, c2 = st.columns([1, 3])
        c1.metric("OBX Index", f"{last:,.1f}", f"{(last/prev-1)*100:+.2f}%")
        fig = px.area(idx, y="Close", title="OBX — last 6 months")
        fig.update_layout(height=260, margin=dict(l=0, r=0, t=40, b=0), showlegend=False)
        c2.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Watchlist")
    q = quotes(tuple(OSLO_UNIVERSE.keys()))
    rows = []
    for t, name in OSLO_UNIVERSE.items():
        d = q.get(t, {})
        p, pc = d.get("price", np.nan), d.get("prev_close", np.nan)
        rows.append({"Ticker": t, "Name": name, "Price": p,
                     "Day %": (p / pc - 1) * 100 if pc else np.nan,
                     "Volume": d.get("volume", np.nan)})
    wl = pd.DataFrame(rows).sort_values("Day %", ascending=False, na_position="last")
    if wl["Price"].notna().any():
        st.dataframe(wl, use_container_width=True, hide_index=True,
                     column_config={
                         "Price": st.column_config.NumberColumn(format="%.2f"),
                         "Day %": st.column_config.NumberColumn(format="%.2f%%"),
                         "Volume": st.column_config.NumberColumn(format="%d")})
        g1, g2 = st.columns(2)
        valid = wl.dropna(subset=["Day %"])
        g1.markdown("**Top movers ▲**")
        g1.dataframe(valid.head(5)[["Name", "Day %"]], hide_index=True, use_container_width=True)
        g2.markdown("**Laggards ▼**")
        g2.dataframe(valid.tail(5)[["Name", "Day %"]], hide_index=True, use_container_width=True)
    else:
        st.warning("Could not load quotes. Check your connection and press Refresh.")

# --------------------------------------------------------------------------- #
# TAB 2 — Stock (chart + fundamentals + news + thesis)
# --------------------------------------------------------------------------- #
with tab_stock:
    st.subheader("Stock explorer")
    with st.expander("ℹ️ How to use this tab"):
        st.write("Deep-dive a single stock. The candlestick chart carries two moving "
                 "averages (SMA20/50) and an RSI panel (below 30 = oversold, above 70 = "
                 "overbought). Fundamentals sit above the chart. Below it you get recent "
                 "headlines — with an optional AI summary if you've set an API key — and a "
                 "private thesis note that's saved per stock so you remember why you own it.")
    a, b, c = st.columns([2, 1, 1])
    picked = a.selectbox("Pick a stock", list(OSLO_UNIVERSE.keys()),
                         format_func=lambda t: f"{OSLO_UNIVERSE.get(t, t)} ({t})")
    custom = b.text_input("…or type a ticker", placeholder="e.g. AAPL, VOW3.DE")
    period = c.selectbox("Period", ["3mo", "6mo", "1y", "2y", "5y"], index=2)
    ticker = custom.strip().upper() or picked

    h = hist(ticker, period=period)
    if h.empty:
        st.error(f"No data for {ticker}. For Oslo Børs use the .OL suffix (e.g. EQNR.OL).")
    else:
        close = h["Close"]
        h = h.assign(SMA20=sma(close, 20), SMA50=sma(close, 50), RSI=rsi(close))
        last = float(close.iloc[-1])
        chg = (last / float(close.iloc[-2]) - 1) * 100
        chg_1m = (last / float(close.iloc[-22]) - 1) * 100 if len(close) > 22 else np.nan
        m = st.columns(4)
        m[0].metric("Last", f"{last:,.2f}", f"{chg:+.2f}%")
        m[1].metric("1-month", f"{chg_1m:+.1f}%" if pd.notna(chg_1m) else "–")
        m[2].metric("52w high", f"{float(close.max()):,.2f}")
        m[3].metric("52w low", f"{float(close.min()):,.2f}")

        f = fundamentals(ticker)
        dy = f.get("dividend_yield")
        dy_pct = dy * 100 if (dy is not None and dy < 1) else dy
        f1, f2, f3, f4 = st.columns(4)
        f1.metric("P/E (trailing)", f"{f['pe']:.1f}" if f.get("pe") else "–")
        f2.metric("Dividend yield", f"{dy_pct:.2f}%" if dy_pct else "–")
        f3.metric("Market cap", big_number(f.get("market_cap")))
        f4.metric("Sector", f.get("sector") or "–")

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                            row_heights=[0.72, 0.28], vertical_spacing=0.04)
        fig.add_trace(go.Candlestick(x=h.index, open=h["Open"], high=h["High"],
                                     low=h["Low"], close=h["Close"], name="Price"), 1, 1)
        fig.add_trace(go.Scatter(x=h.index, y=h["SMA20"], name="SMA20", line=dict(width=1)), 1, 1)
        fig.add_trace(go.Scatter(x=h.index, y=h["SMA50"], name="SMA50", line=dict(width=1)), 1, 1)
        fig.add_trace(go.Scatter(x=h.index, y=h["RSI"], name="RSI", line=dict(width=1)), 2, 1)
        fig.add_hline(y=70, line_dash="dot", row=2, col=1)
        fig.add_hline(y=30, line_dash="dot", row=2, col=1)
        fig.update_layout(height=520, xaxis_rangeslider_visible=False,
                          margin=dict(l=0, r=0, t=10, b=0),
                          legend=dict(orientation="h", y=1.02))
        fig.update_yaxes(title_text="RSI", range=[0, 100], row=2, col=1)
        st.plotly_chart(fig, use_container_width=True)

        col_news, col_note = st.columns(2)
        with col_news:
            st.markdown("##### 📰 Latest news")
            items = news(ticker)
            if not items:
                st.caption("No headlines available.")
            else:
                summary = summarize_news(ticker, items)
                if summary:
                    st.info(summary)
                else:
                    st.caption("Set ANTHROPIC_API_KEY (and `pip install anthropic`) "
                               "for an AI summary.")
                for it in items[:6]:
                    if it.get("link"):
                        st.markdown(f"- [{it['title']}]({it['link']}) "
                                    f"· *{it.get('publisher','')}*")
                    else:
                        st.markdown(f"- {it['title']} · *{it.get('publisher','')}*")
        with col_note:
            st.markdown("##### 📝 My thesis & checklist")
            existing = store.get_note(ticker)
            txt = st.text_area("Why do I own / watch this?", value=existing, height=180,
                               key=f"note_{ticker}",
                               placeholder="Thesis, target price, risks, what would "
                                           "change my mind…")
            if st.button("Save note", key=f"savenote_{ticker}"):
                store.set_note(ticker, txt)
                st.success("Saved.")

# --------------------------------------------------------------------------- #
# TAB 3 — Portfolio
# --------------------------------------------------------------------------- #
with tab_portfolio:
    st.subheader("Portfolio")
    with st.expander("ℹ️ How to use this tab"):
        st.write("Your holdings are built from a transaction ledger, so the numbers are "
                 "honest. Record a **DEPOSIT** first, then **BUY**/**SELL** trades and any "
                 "**DIV** dividends. The app derives open positions, realised and unrealised "
                 "P/L, cash, and total value, and charts your **time-weighted** return "
                 "against the OBX — time-weighting means adding money never flatters the "
                 "line, so it's a fair comparison to the index.")
    st.caption(f"Active portfolio: **{active_portfolio}**")
    tx = store.get_transactions(active_portfolio)

    with st.expander("📥 Import transactions from a broker CSV"):
        up = st.file_uploader("CSV export (Nordnet, DNB, Saxo…)", type=["csv"])
        if up is not None:
            try:
                raw = pd.read_csv(up, sep=None, engine="python")
            except Exception:
                up.seek(0)
                raw = pd.read_csv(up, sep=";")
            st.caption(f"{len(raw)} rows. Map the columns below.")
            cols = ["—"] + list(raw.columns)

            def guess(cands):
                for i, c in enumerate(raw.columns):
                    if any(k in c.lower() for k in cands):
                        return i + 1
                return 0
            m1, m2, m3 = st.columns(3)
            map_date = m1.selectbox("Date", cols, index=guess(["date", "dato"]))
            map_tick = m2.selectbox("Ticker", cols, index=guess(["ticker", "verdipapir", "symbol", "papper"]))
            map_type = m3.selectbox("Type", cols, index=guess(["type", "transaksjon", "event"]))
            m4, m5, m6 = st.columns(3)
            map_qty = m4.selectbox("Quantity", cols, index=guess(["antall", "quantity", "qty", "volume"]))
            map_prc = m5.selectbox("Price", cols, index=guess(["kurs", "price", "pris"]))
            map_fee = m6.selectbox("Fee (optional)", cols, index=guess(["avgift", "fee", "courtage", "kurtasje"]))
            if "—" not in (map_date, map_tick, map_type, map_qty, map_prc):
                mapping = {"date": map_date, "ticker": map_tick, "type": map_type,
                           "quantity": map_qty, "price": map_prc}
                if map_fee != "—":
                    mapping["fee"] = map_fee
                norm = imp.normalize_transactions(raw, mapping)
                st.write(f"**{len(norm)}** recognised transactions preview:")
                st.dataframe(norm.head(20), use_container_width=True, hide_index=True)
                if st.button(f"Import {len(norm)} into '{active_portfolio}'"):
                    for _, r in norm.iterrows():
                        store.add_transaction(r["date"], r["ticker"], r["type"],
                                              quantity=r["quantity"], price=r["price"],
                                              fee=r["fee"], portfolio=active_portfolio)
                    st.success(f"Imported {len(norm)} transactions.")
                    st.rerun()
            else:
                st.info("Pick a column for date, ticker, type, quantity and price.")

    with st.expander("➕ Record a transaction", expanded=tx.empty):
        st.caption("**BUY / SELL:** Quantity + Price.  **DIV:** cash in Price, Qty 0.  "
                   "**DEPOSIT / WITHDRAW:** cash amount in Price, Qty 0.")
        with st.form("add_tx", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            tk = c1.selectbox("Ticker", list(OSLO_UNIVERSE.keys()),
                              format_func=lambda x: f"{x} · {OSLO_UNIVERSE.get(x, x)}")
            tk_custom = c1.text_input("or custom ticker", placeholder="EQNR.OL")
            ttype = c2.selectbox("Type", ["BUY", "SELL", "DIV", "DEPOSIT", "WITHDRAW"])
            dt = c2.date_input("Date", value=date.today())
            qty = c3.number_input("Quantity", min_value=0.0, value=10.0, step=1.0)
            prc = c3.number_input("Price / cash amount", min_value=0.0, value=0.0, step=0.5,
                                  help="Per-share price for BUY/SELL (0 = latest market "
                                       "price); cash amount for DIV/DEPOSIT/WITHDRAW.")
            fee = c1.number_input("Fee", min_value=0.0, value=29.0, step=1.0)
            note = c2.text_input("Note", placeholder="optional")
            if st.form_submit_button("Save transaction"):
                symbol = "CASH" if ttype in ("DEPOSIT", "WITHDRAW") else (tk_custom.strip().upper() or tk)
                p = prc
                if ttype in ("BUY", "SELL") and prc == 0:
                    p = price_now(symbol)
                store.add_transaction(dt, symbol, ttype, quantity=qty, price=p, fee=fee,
                                      note=note, portfolio=active_portfolio)
                st.success(f"Recorded {ttype} {symbol}")
                st.rerun()

    if tx.empty:
        st.info("No transactions yet. Record a deposit and a buy above to start tracking.")
    else:
        method = st.radio("Cost-basis method", ["Average cost", "FIFO (Norwegian tax)"],
                          horizontal=True,
                          help="FIFO matches Norway's first-in-first-out rule for share "
                               "disposals, so realised P/L reflects the oldest lots first.")
        pos = (taxlots.fifo_positions(tx) if method.startswith("FIFO")
               else store.compute_positions(tx))
        pos["name"] = pos["ticker"].map(lambda t: OSLO_UNIVERSE.get(t, t))
        pos["ccy"] = pos["ticker"].map(lambda t: quote(t).get("currency", "NOK"))
        pos["price_now"] = pos["ticker"].map(price_now)
        pos["rate"] = pos["ccy"].map(fx_rate).fillna(1.0)
        pos["cost_basis"] = pos["shares"] * pos["avg_cost"]
        pos["value_nok"] = pos["shares"] * pos["price_now"] * pos["rate"]
        pos["cost_nok"] = pos["cost_basis"] * pos["rate"]
        pos["unrealised"] = pos["value_nok"] - pos["cost_nok"]
        pos["unreal_%"] = np.where(pos["cost_nok"] > 0,
                                   pos["unrealised"] / pos["cost_nok"] * 100, np.nan)

        holdings_nok = pos["value_nok"].sum()
        unreal = pos["unrealised"].sum()
        realised = (pos["realised"] * pos["rate"]).sum()
        dividends = (pos["dividends"] * pos["rate"]).sum()
        cash = store.compute_cash(tx)
        total_value = holdings_nok + cash
        net_dep = store.net_deposits(tx)

        r1 = st.columns(3)
        r1[0].metric("Holdings value", money(holdings_nok))
        r1[1].metric("Cash", money(cash))
        r1[2].metric("Total value", money(total_value),
                     f"{((total_value-net_dep)/net_dep*100):+.1f}%" if net_dep else None)
        r2 = st.columns(3)
        r2[0].metric("Unrealised P/L", money(unreal))
        r2[1].metric("Realised P/L", money(realised))
        r2[2].metric("Dividends", money(dividends))

        st.markdown("#### Positions")
        open_pos = pos[pos["shares"] > 1e-6]
        view = open_pos.rename(columns={"name": "Name", "shares": "Shares", "ccy": "Ccy",
                                        "avg_cost": "Avg cost", "price_now": "Now",
                                        "value_nok": "Value (NOK)", "unrealised": "Unreal P/L"})
        if not view.empty:
            st.dataframe(
                view[["Name", "Ccy", "Shares", "Avg cost", "Now",
                      "Value (NOK)", "Unreal P/L", "unreal_%"]],
                use_container_width=True, hide_index=True,
                column_config={
                    "Avg cost": st.column_config.NumberColumn(format="%.2f"),
                    "Now": st.column_config.NumberColumn(format="%.2f"),
                    "Value (NOK)": st.column_config.NumberColumn(format="%.0f"),
                    "Unreal P/L": st.column_config.NumberColumn(format="%.0f"),
                    "unreal_%": st.column_config.NumberColumn("Unreal %", format="%.1f%%")})
            pie = px.pie(open_pos, names="name", values="value_nok", title="Allocation", hole=0.45)
            pie.update_layout(height=320, margin=dict(t=40, b=0, l=0, r=0))
            st.plotly_chart(pie, use_container_width=True)

        if method.startswith("FIFO"):
            with st.expander("🧾 FIFO tax report — realised disposals"):
                rep = taxlots.fifo_realised(tx)
                if rep.empty:
                    st.caption("No sales yet — nothing realised.")
                else:
                    show = rep.rename(columns={
                        "ticker": "Ticker", "acquired": "Acquired", "disposed": "Disposed",
                        "shares": "Shares", "cost": "Cost", "proceeds": "Proceeds",
                        "gain": "Gain", "holding_days": "Held (days)"})
                    st.dataframe(show, use_container_width=True, hide_index=True,
                                 column_config={
                                     "Cost": st.column_config.NumberColumn(format="%.0f"),
                                     "Proceeds": st.column_config.NumberColumn(format="%.0f"),
                                     "Gain": st.column_config.NumberColumn(format="%.0f")})
                    st.metric("Total realised gain (FIFO)", money(rep["gain"].sum()))
                st.caption("Each sale matched against the oldest lots. Bookkeeping only — "
                           "confirm shielding deduction and fee treatment with a tax adviser.")

        # time-weighted performance vs OBX
        st.markdown("#### Performance vs OBX (time-weighted)")
        trades = tx[tx["type"].isin(["BUY", "SELL"])]
        if trades.empty:
            st.caption("Record at least one BUY to see a performance history.")
        else:
            first_dt = pd.to_datetime(trades["date"]).min().date()
            per = period_for(first_dt)
            try:
                price_df = price_frame(sorted(trades["ticker"].unique()), per)
                price_df = price_df[price_df.index >= pd.Timestamp(first_dt)]
                shares = pf.shares_over_time(tx, price_df.index)
                value = pf.holdings_value(shares, price_df)
                flows = pf.external_flows(tx, price_df.index)
                twr = pf.twr_index(value, flows).dropna()
                if len(twr) > 2:
                    obx = hist(INDEX_TICKER, period=per)["Close"]
                    obx.index = naive_index(obx.index)
                    obx = obx[obx.index >= twr.index[0]]
                    obx = obx / obx.iloc[0]
                    comp = pd.DataFrame({"My portfolio": twr, "OBX index": obx}).ffill()
                    pr, orr = (twr.iloc[-1]-1)*100, (obx.iloc[-1]-1)*100
                    mm = st.columns(3)
                    mm[0].metric("Portfolio return", f"{pr:+.1f}%", f"{pr-orr:+.1f}% vs OBX")
                    mm[1].metric("OBX return", f"{orr:+.1f}%")
                    mm[2].metric("Max drawdown", f"{max_drawdown(twr):.1f}%")
                    figp = px.line(comp, title="Growth of 1 — your choices vs the index")
                    figp.update_layout(height=340, margin=dict(t=40, b=0, l=0, r=0),
                                       legend=dict(orientation="h", y=1.05), yaxis_title="Growth of 1")
                    st.plotly_chart(figp, use_container_width=True)
            except Exception as e:
                st.warning(f"Could not build the performance chart: {e}")

        st.markdown("#### Transaction ledger")
        led = tx.rename(columns={"date": "Date", "ticker": "Ticker", "type": "Type",
                                 "quantity": "Qty", "price": "Price", "fee": "Fee"})
        st.dataframe(led[["id", "Date", "Ticker", "Type", "Qty", "Price", "Fee", "note"]],
                     use_container_width=True, hide_index=True)

        exp = st.columns(3)
        exp[0].download_button(
            "⬇️ Transactions CSV", tx.to_csv(index=False),
            f"transactions_{active_portfolio}.csv", "text/csv", use_container_width=True)
        if not pos.empty:
            pcols = ["ticker", "name", "shares", "avg_cost", "price_now",
                     "value_nok", "unrealised", "realised", "dividends"]
            exp[1].download_button(
                "⬇️ Positions CSV", pos[pcols].to_csv(index=False),
                f"positions_{active_portfolio}.csv", "text/csv", use_container_width=True)
        if method.startswith("FIFO"):
            exp[2].download_button(
                "⬇️ FIFO tax report CSV", taxlots.fifo_realised(tx).to_csv(index=False),
                f"fifo_report_{active_portfolio}.csv", "text/csv", use_container_width=True)

        cdel, _ = st.columns([2, 1])
        del_id = cdel.selectbox(
            "Delete a transaction", options=list(tx["id"]),
            format_func=lambda i: (f"#{i} · {tx.loc[tx.id==i,'type'].iloc[0]} "
                                   f"{tx.loc[tx.id==i,'ticker'].iloc[0]} on {tx.loc[tx.id==i,'date'].iloc[0]}"))
        if cdel.button("🗑️ Delete selected"):
            store.delete_transaction(del_id)
            st.rerun()

# --------------------------------------------------------------------------- #
# TAB 4 — Simulator (lump-sum, DCA/rebalance backtest, Monte Carlo)
# --------------------------------------------------------------------------- #
with tab_sim:
    st.subheader("Simulations")
    with st.expander("ℹ️ How to use this tab"):
        st.write("Three what-if tools. **Lump-sum** shows how a one-off investment in one "
                 "stock would have grown. **DCA & rebalance** backtests a basket with an "
                 "up-front amount plus monthly contributions, optionally rebalancing to "
                 "equal weights, and reports XIRR (your true annualised return). **Monte "
                 "Carlo** projects a fan of future outcomes from the historical return "
                 "profile — a range of possibilities, not a forecast.")
    mode = st.radio("Simulation", ["Lump-sum single stock", "Basket: DCA & rebalance",
                                    "Monte Carlo projection"], horizontal=True)

    if mode == "Lump-sum single stock":
        c1, c2, c3 = st.columns(3)
        tk = c1.selectbox("Stock", list(OSLO_UNIVERSE.keys()),
                          format_func=lambda x: f"{OSLO_UNIVERSE.get(x, x)} ({x})")
        amount = c2.number_input(f"Amount ({CURRENCY})", min_value=100.0, value=10000.0, step=1000.0)
        start = c3.date_input("Invested on", value=date(date.today().year - 3, 1, 1))
        h = hist(tk, period="5y")
        if not h.empty:
            h = h[h.index.date >= start]
            if len(h) > 1:
                shares = amount / float(h["Close"].iloc[0])
                h = h.assign(value=h["Close"] * shares)
                end_val = float(h["value"].iloc[-1])
                years = max((h.index[-1] - h.index[0]).days / 365.25, 0.01)
                cagr = (end_val / amount) ** (1 / years) - 1
                m = st.columns(3)
                m[0].metric("Value today", money(end_val), f"{(end_val/amount-1)*100:+.1f}%")
                m[1].metric("Annualised (CAGR)", f"{cagr*100:+.1f}%")
                m[2].metric("Shares bought", f"{shares:,.1f}")
                fig = px.area(h, y="value", title=f"{amount:,.0f} {CURRENCY} in {tk}")
                fig.update_layout(height=340, margin=dict(t=40, b=0, l=0, r=0))
                st.plotly_chart(fig, use_container_width=True)

    elif mode == "Basket: DCA & rebalance":
        picks = st.multiselect("Basket", list(OSLO_UNIVERSE.keys()),
                               default=["EQNR.OL", "DNB.OL", "MOWI.OL", "TEL.OL"],
                               format_func=lambda x: f"{OSLO_UNIVERSE.get(x, x)} ({x})")
        c1, c2, c3, c4 = st.columns(4)
        look = c1.selectbox("Lookback", ["1y", "2y", "5y"], index=1)
        initial = c2.number_input("Initial (NOK)", min_value=0.0, value=10000.0, step=1000.0)
        monthly = c3.number_input("Monthly (NOK)", min_value=0.0, value=1000.0, step=500.0)
        reb = c4.selectbox("Rebalance", ["none", "monthly", "quarterly", "annual"], index=2)
        if picks:
            price_df = price_frame(picks, look)
            if len(price_df) > 5:
                weights = {p: 1.0 for p in picks}  # equal weight
                value_s, inv_s, cfs = an.dca_backtest(price_df, weights, initial, monthly, reb)
                irr = an.xirr(cfs)
                rm = an.risk_metrics(value_s.pct_change())
                m = st.columns(4)
                m[0].metric("Invested", money(inv_s.iloc[-1]))
                m[1].metric("Value", money(value_s.iloc[-1]),
                            f"{(value_s.iloc[-1]/inv_s.iloc[-1]-1)*100:+.1f}%" if inv_s.iloc[-1] else None)
                m[2].metric("Annualised (XIRR)", f"{irr*100:+.1f}%" if pd.notna(irr) else "–")
                m[3].metric("Max drawdown", f"{rm.get('max_dd', float('nan')):.1f}%")
                comp = pd.DataFrame({"Portfolio value": value_s, "Money invested": inv_s})
                fig = px.line(comp, title="DCA growth vs money invested")
                fig.update_layout(height=360, margin=dict(t=40, b=0, l=0, r=0),
                                  legend=dict(orientation="h", y=1.05))
                st.plotly_chart(fig, use_container_width=True)
                st.caption(f"Equal-weighted, rebalanced **{reb}**. Volatility "
                           f"{rm.get('vol', float('nan')):.1f}%, Sortino "
                           f"{rm.get('sortino', float('nan')):.2f}.")
            else:
                st.info("Not enough overlapping history for these tickers.")

    else:  # Monte Carlo
        st.caption("Projects a distribution of future outcomes by resampling the "
                   "historical return profile. Illustrative, not a forecast.")
        c1, c2, c3, c4 = st.columns(4)
        src = c1.selectbox("Based on", ["My portfolio"] + list(OSLO_UNIVERSE.keys()),
                           format_func=lambda x: OSLO_UNIVERSE.get(x, x))
        start_val = c2.number_input("Start value (NOK)", min_value=1000.0, value=100000.0, step=10000.0)
        horizon = c3.selectbox("Horizon", ["1 year", "3 years", "5 years"], index=1)
        n_sims = c4.selectbox("Simulations", [500, 1000, 5000], index=1)
        days = {"1 year": 252, "3 years": 756, "5 years": 1260}[horizon]

        if src == "My portfolio":
            tx = store.get_transactions(active_portfolio)
            trades = tx[tx["type"].isin(["BUY", "SELL"])] if not tx.empty else pd.DataFrame()
            if trades.empty:
                ret = None
                st.info("No holdings yet — pick a stock instead, or build a portfolio first.")
            else:
                pdf = price_frame(sorted(trades["ticker"].unique()), "2y")
                sh = pf.shares_over_time(tx, pdf.index)
                val = pf.holdings_value(sh, pdf)
                ret = val.pct_change()
        else:
            ret = hist(src, period="2y")["Close"].pct_change()

        if ret is not None and ret.dropna().shape[0] > 20:
            bands, ends = an.monte_carlo(ret, start_val, days=days, n=int(n_sims))
            x = list(range(len(bands[50])))
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=x, y=bands[95], line=dict(width=0), showlegend=False))
            fig.add_trace(go.Scatter(x=x, y=bands[5], fill="tonexty", name="5–95%",
                                     line=dict(width=0), fillcolor="rgba(99,110,250,0.15)"))
            fig.add_trace(go.Scatter(x=x, y=bands[75], line=dict(width=0), showlegend=False))
            fig.add_trace(go.Scatter(x=x, y=bands[25], fill="tonexty", name="25–75%",
                                     line=dict(width=0), fillcolor="rgba(99,110,250,0.30)"))
            fig.add_trace(go.Scatter(x=x, y=bands[50], name="Median", line=dict(width=2)))
            fig.update_layout(height=380, title="Projected value (fan chart)",
                              margin=dict(t=40, b=0, l=0, r=0),
                              legend=dict(orientation="h", y=1.05),
                              xaxis_title="Trading days ahead", yaxis_title="Value (NOK)")
            st.plotly_chart(fig, use_container_width=True)
            m = st.columns(3)
            m[0].metric("Median outcome", money(np.median(ends)))
            m[1].metric("5th percentile", money(np.percentile(ends, 5)))
            m[2].metric("95th percentile", money(np.percentile(ends, 95)))

# --------------------------------------------------------------------------- #
# TAB 5 — Risk (correlation, beta, risk metrics)
# --------------------------------------------------------------------------- #
with tab_risk:
    st.subheader("Risk & diversification")
    with st.expander("ℹ️ How to use this tab"):
        st.write("See how risky your holdings are and how much they move together. The "
                 "correlation heatmap shows diversification — lower (bluer) pairs cushion "
                 "each other. The table gives each stock's beta vs the OBX (>1 = swingier "
                 "than the market), annualised volatility, Sortino ratio (return per unit of "
                 "downside risk), daily Value-at-Risk, and worst drawdown. It defaults to "
                 "your current holdings.")
    tx = store.get_transactions(active_portfolio)
    held = []
    if not tx.empty:
        p = store.compute_positions(tx)
        held = list(p[p["shares"] > 1e-6]["ticker"])
    default_sel = held if held else ["EQNR.OL", "DNB.OL", "MOWI.OL", "TEL.OL"]
    sel = st.multiselect("Stocks to analyse", list(OSLO_UNIVERSE.keys()),
                         default=default_sel,
                         format_func=lambda x: f"{OSLO_UNIVERSE.get(x, x)} ({x})")
    look = st.selectbox("Lookback", ["1y", "2y", "5y"], index=1)

    if len(sel) >= 1:
        price_df = price_frame(sel, look)
        if len(price_df) > 20:
            rets = an.daily_returns(price_df)
            obx = hist(INDEX_TICKER, period=look)["Close"]
            obx.index = naive_index(obx.index)
            obx_ret = obx.reindex(price_df.index).ffill().pct_change()

            if len(sel) >= 2:
                st.markdown("#### Correlation of daily returns")
                cm = an.correlation_matrix(price_df)
                heat = px.imshow(cm, text_auto=".2f", color_continuous_scale="RdBu_r",
                                 zmin=-1, zmax=1, aspect="auto")
                heat.update_layout(height=380, margin=dict(t=10, b=0, l=0, r=0))
                st.plotly_chart(heat, use_container_width=True)
                st.caption("Lower correlations = more diversification benefit.")

            st.markdown("#### Per-stock risk vs OBX")
            table = []
            for t in sel:
                r = rets[t].dropna()
                rm = an.risk_metrics(r)
                table.append({
                    "Stock": OSLO_UNIVERSE.get(t, t),
                    "Beta": an.beta(r, obx_ret),
                    "Volatility %": rm.get("vol", np.nan),
                    "Sortino": rm.get("sortino", np.nan),
                    "VaR 95% (daily)": rm.get("var95_daily", np.nan),
                    "Max DD %": rm.get("max_dd", np.nan)})
            df = pd.DataFrame(table)
            st.dataframe(df, use_container_width=True, hide_index=True,
                         column_config={
                             "Beta": st.column_config.NumberColumn(format="%.2f"),
                             "Volatility %": st.column_config.NumberColumn(format="%.1f"),
                             "Sortino": st.column_config.NumberColumn(format="%.2f"),
                             "VaR 95% (daily)": st.column_config.NumberColumn(format="%.2f"),
                             "Max DD %": st.column_config.NumberColumn(format="%.1f")})
            st.caption("Beta >1 = more volatile than the OBX. VaR 95% ≈ the daily loss "
                       "you'd exceed only 5% of days. Sortino rewards return per unit of "
                       "downside risk.")

            if len(sel) >= 2:
                st.markdown("#### Efficient frontier")
                cloud, hi = an.efficient_frontier(price_df, n=3000)
                fig = px.scatter(cloud, x="vol", y="ret", color="sharpe",
                                 color_continuous_scale="Viridis",
                                 labels={"vol": "Volatility %", "ret": "Return %",
                                         "sharpe": "Sharpe"},
                                 title="Random long-only portfolios (annualised)")
                for label, sym, key in [("Max Sharpe", "star", "max_sharpe"),
                                        ("Min volatility", "diamond", "min_vol")]:
                    fig.add_trace(go.Scatter(
                        x=[hi[key]["vol"]], y=[hi[key]["ret"]], mode="markers+text",
                        marker=dict(size=15, symbol=sym, color="#0B6E7A",
                                    line=dict(width=1, color="white")),
                        text=[label], textposition="top center", name=label,
                        showlegend=False))
                fig.update_layout(height=420, margin=dict(t=40, b=0, l=0, r=0))
                st.plotly_chart(fig, use_container_width=True)
                w = hi["max_sharpe"]["weights"]
                wtxt = ", ".join(f"{OSLO_UNIVERSE.get(k, k)} {v*100:.0f}%"
                                 for k, v in sorted(w.items(), key=lambda x: -x[1]) if v > 0.005)
                st.caption(f"**Max-Sharpe mix:** {wtxt}. Each dot is a random weighting; "
                           "the frontier is its upper-left edge (most return per unit of risk). "
                           "Backward-looking — past performance won't repeat.")
        else:
            st.info("Not enough overlapping history for these tickers.")

# --------------------------------------------------------------------------- #
# TAB 6 — Screener & signals
# --------------------------------------------------------------------------- #
with tab_screener:
    st.subheader("Screener & signals")
    with st.expander("ℹ️ How to use this tab"):
        st.write("Two ways to find and judge ideas. **Fundamentals screener** filters the "
                 "whole universe by P/E, dividend yield and market cap to surface "
                 "candidates. **Configurable signals** scores stocks on transparent "
                 "trend/momentum rules whose thresholds and weights you control — so the "
                 "score reflects *your* logic, not a black box. Both are research aids, "
                 "never buy/sell advice.")
    sub = st.radio("View", ["Fundamentals screener", "Configurable signals"], horizontal=True)

    if sub == "Fundamentals screener":
        st.caption("Filter the universe on fundamentals. Data via Yahoo; some fields "
                   "may be missing for smaller names.")
        f1, f2, f3 = st.columns(3)
        max_pe = f1.slider("Max P/E", 0, 60, 30)
        min_yield = f2.slider("Min dividend yield %", 0.0, 10.0, 0.0, 0.5)
        min_cap_b = f3.slider("Min market cap (NOK bn)", 0, 200, 0)

        rows = []
        for t, name in OSLO_UNIVERSE.items():
            f = fundamentals(t)
            dy = f.get("dividend_yield")
            dy_pct = dy * 100 if (dy is not None and dy < 1) else (dy or 0)
            rows.append({"Ticker": t, "Name": name, "P/E": f.get("pe"),
                         "Div yield %": dy_pct, "Market cap": f.get("market_cap"),
                         "Sector": f.get("sector")})
        scr = pd.DataFrame(rows)
        mask = (
            (scr["P/E"].fillna(9999) <= max_pe) &
            (scr["Div yield %"].fillna(0) >= min_yield) &
            (scr["Market cap"].fillna(0) >= min_cap_b * 1e9))
        out = scr[mask].sort_values("Div yield %", ascending=False)
        st.write(f"**{len(out)}** of {len(scr)} stocks match.")
        show = out.copy()
        show["Market cap"] = show["Market cap"].map(big_number)
        st.dataframe(show, use_container_width=True, hide_index=True,
                     column_config={
                         "P/E": st.column_config.NumberColumn(format="%.1f"),
                         "Div yield %": st.column_config.NumberColumn(format="%.2f")})

    else:
        st.caption("Tune the mechanical scoring rules. Transparent by design — **not** advice.")
        c1, c2, c3 = st.columns(3)
        rsi_os = c1.slider("RSI oversold <", 10, 40, 30)
        rsi_ob = c1.slider("RSI overbought >", 60, 90, 70)
        mom_thr = c2.slider("Momentum threshold % (1m)", 1, 20, 5)
        w_trend = c2.slider("Weight: trend (vs SMA50)", 0, 3, 1)
        w_cross = c3.slider("Weight: SMA20>SMA50", 0, 3, 1)
        w_rsi = c3.slider("Weight: RSI", 0, 3, 1)
        w_mom = c3.slider("Weight: momentum", 0, 3, 1)

        def score(tk):
            h = hist(tk, period="1y")
            if len(h) < 60:
                return None
            c = h["Close"]
            s20, s50, r = sma(c, 20).iloc[-1], sma(c, 50).iloc[-1], rsi(c).iloc[-1]
            mom = (c.iloc[-1] / c.iloc[-22] - 1) * 100 if len(c) > 22 else 0
            pts, why = 0, []
            pts += w_trend * (1 if c.iloc[-1] > s50 else -1)
            why.append("↑SMA50" if c.iloc[-1] > s50 else "↓SMA50")
            pts += w_cross * (1 if s20 > s50 else -1)
            if r < rsi_os:
                pts += w_rsi; why.append(f"RSI {r:.0f} oversold")
            elif r > rsi_ob:
                pts -= w_rsi; why.append(f"RSI {r:.0f} overbought")
            if mom > mom_thr:
                pts += w_mom; why.append(f"mom {mom:+.0f}%")
            elif mom < -mom_thr:
                pts -= w_mom; why.append(f"mom {mom:+.0f}%")
            label = "🟢 Constructive" if pts >= 2 else "🔴 Weak" if pts <= -2 else "🟡 Neutral"
            return {"Ticker": tk, "Name": OSLO_UNIVERSE.get(tk, tk),
                    "Score": pts, "Signal": label, "Why": ", ".join(why)}

        picks = st.multiselect("Stocks", list(OSLO_UNIVERSE.keys()),
                               default=list(OSLO_UNIVERSE.keys())[:10],
                               format_func=lambda x: f"{OSLO_UNIVERSE.get(x, x)} ({x})")
        if picks:
            res = [s for tk in picks if (s := score(tk))]
            if res:
                st.dataframe(pd.DataFrame(res).sort_values("Score", ascending=False),
                             use_container_width=True, hide_index=True)
        st.info("Backward-looking and simplistic. Check fundamentals, news and your own "
                "risk tolerance before acting. Not financial advice.")
