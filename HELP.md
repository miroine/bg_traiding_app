# Help & glossary

In-app help lives under the **ℹ️ How to use this tab** panel on each tab. This file
is the fuller reference — what each screen is for, and what the numbers mean.

## 🌍 Market
The market's pulse. The OBX index chart is the broad Oslo Børs benchmark over six
months. The watchlist ranks tracked names by today's percentage move; top movers and
laggards are pulled out below. To track different stocks, edit `OSLO_UNIVERSE` at the
top of `app.py` (Oslo Børs tickers end in `.OL`, e.g. `EQNR.OL`).

## 🔍 Stock
Everything about one stock:
- **Chart** — candlesticks with SMA20 and SMA50 (short vs medium trend). The lower
  panel is RSI: below 30 is often called oversold, above 70 overbought.
- **Fundamentals** — trailing P/E, dividend yield, market cap, sector.
- **News** — recent headlines. Set `ANTHROPIC_API_KEY` for a short AI summary.
- **Thesis note** — your private reason for owning/watching it, saved per stock.

## 💼 Portfolio
Built from a **ledger** of transactions, so it reflects reality including sells and
dividends. Record types:
- **DEPOSIT / WITHDRAW** — cash in/out (put the amount in the Price field).
- **BUY / SELL** — quantity + per-share price (leave price 0 to use the latest).
- **DIV** — total dividend cash in the Price field.

Numbers explained:
- **Unrealised P/L** — paper gain/loss on what you still hold.
- **Realised P/L** — locked-in gain/loss from what you've sold (average-cost method).
- **Total value** — holdings + cash.
- **Performance vs OBX** — a *time-weighted* return index. Time-weighting removes the
  effect of deposits, so buying more never fakes a higher return; it's the fair way to
  compare yourself to the index.

## 🧪 Simulator
- **Lump-sum** — how a one-off investment in a single stock would have grown.
- **DCA & rebalance** — backtest an equal-weight basket with an initial amount plus a
  monthly contribution, optionally rebalancing. **XIRR** is your true annualised return
  given the timing of every contribution.
- **Monte Carlo** — simulates thousands of possible future paths from the historical
  return profile and shows the 5–95% range. A spread of possibilities, not a forecast.

## 📊 Risk
- **Correlation heatmap** — how much holdings move together. Lower (bluer) = better
  diversification.
- **Beta** — sensitivity to the OBX. 1.0 moves with the market; >1 amplifies it.
- **Volatility** — annualised standard deviation of returns.
- **Sortino** — return per unit of *downside* risk (higher is better).
- **VaR 95% (daily)** — a daily loss you'd exceed only about 5% of days.
- **Max drawdown** — worst peak-to-trough fall over the window.

## 🔎 Screener & signals
- **Fundamentals screener** — filter the whole universe by max P/E, minimum dividend
  yield, and minimum market cap to surface candidates.
- **Configurable signals** — a transparent score from trend/momentum rules. You set the
  RSI thresholds, the momentum cut-off, and the weight of each rule, so the score
  encodes your logic. 🟢/🟡/🔴 summarise it. It is a research aid, never advice.

---
*Data is delayed ~15 minutes (Yahoo Finance). Nothing here is financial advice.*

---

## Extra features (sidebar & beyond)

**Multiple portfolios** — use the sidebar selector to switch between portfolios or
create a new one (type a name under "➕ New portfolio…"). The Portfolio, Risk and
Monte Carlo views all scope to the active portfolio.

**Broker-CSV import** (Portfolio tab → 📥) — upload a CSV export from your broker,
match its columns to date / ticker / type / quantity / price / fee, preview the
recognised rows, and import them into the active portfolio. Norwegian/Swedish action
words like *Kjøpt, Solgt, Utbytte, Innskudd* are translated automatically.

**Efficient frontier** (Risk tab, needs ≥2 stocks) — thousands of random long-only
weightings plotted as risk vs return; the star marks the best risk-adjusted mix
(max Sharpe) and the diamond the calmest (min volatility). It's backward-looking, so
treat the "optimal" mix as a discussion starter, not a target.

**Alerts** (Market tab → 🔔) — set a trigger such as "EQNR.OL price above 350" or
"NAS.OL RSI below 30". Triggered alerts show as a banner at the top of the Market tab.
They're evaluated when the app loads or refreshes — a local Streamlit app can't watch
prices in the background.

## Cost-basis method (Portfolio tab)
Toggle between **Average cost** (simple, good for tracking performance) and
**FIFO (Norwegian tax)**, which matches Norway's first-in-first-out rule for share
disposals. FIFO adds a **tax report** listing each sale matched to the lots it drew
from, with acquisition/disposal dates, holding period and realised gain. It's
bookkeeping, not tax advice — confirm shielding-deduction and fee treatment with an adviser.

## Real-time data
By default the app uses free, ~15-min-delayed Yahoo data. To use a paid real-time
feed, set `DATA_PROVIDER=eodhd` and `EODHD_API_KEY`. The active source is shown in the
sidebar. Adding another vendor is just a new class in `providers.py`.

## Alert delivery (email / push)
The Market tab checks alerts when you open or refresh. For monitoring while the app is
closed, run `alert_runner.py` on a schedule (cron / Task Scheduler). Configure delivery
with `NTFY_TOPIC` (free push via ntfy.sh) or the `SMTP_*` variables (email). Use the
**Send test notification** button in the alerts panel to confirm it works.

## Editable watchlist (sidebar)
The tracked stocks are no longer hard-coded. Open **⭐ Manage watchlist** in the sidebar
to add a ticker (e.g. `NEL.OL` — its name is looked up automatically) or remove one.
Changes are saved to the database; the built-in Oslo Børs names are just the initial
seed, and if you ever clear the list it falls back to those defaults.

## Exporting your data (Portfolio tab)
Below the transaction ledger there are download buttons for your **transactions**,
current **positions**, and — in FIFO mode — the **tax report**, all as CSV, scoped to the
active portfolio. Handy for spreadsheets, backups, or handing figures to an accountant.
