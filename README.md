# Oslo Børs Trading Desk 📈

A personal Streamlit app for the Norwegian market: follow stocks, track a real
portfolio from a transaction ledger, run simulations, and pressure-test ideas —
all in NOK. **Delayed data · not financial advice.**

![tabs](https://img.shields.io/badge/tabs-6-0B6E7A) ![tests](https://img.shields.io/badge/tests-passing-2e7d32)

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Opens at http://localhost:8501. Your data is saved locally to `portfolio.db`.

## The six tabs

| Tab | What it does |
|---|---|
| 🌍 **Market** | OBX index + a watchlist of liquid Oslo Børs names, top movers & laggards. |
| 🔍 **Stock** | Candlestick + SMA20/50 + RSI, fundamentals, recent news (optional AI summary), and a saved thesis note per stock. |
| 💼 **Portfolio** | Transaction ledger → positions, realised/unrealised P/L, dividends, cash, total value, and a time-weighted performance chart vs OBX. |
| 🧪 **Simulator** | Lump-sum growth, a DCA + rebalancing backtest with XIRR, and a Monte Carlo fan chart. |
| 📊 **Risk** | Correlation heatmap plus per-stock beta, volatility, Sortino, VaR and drawdown. |
| 🔎 **Screener & signals** | Filter the universe by P/E / yield / market cap, and score stocks with rules whose weights *you* set. |

Every tab has an **ℹ️ How to use this tab** panel at the top, and there's a fuller
`HELP.md` in the repo.

## Configuration (env vars)

| Variable | Effect |
|---|---|
| `PORTFOLIO_DB` | Path to the SQLite file (point at a persistent volume in production). |
| `APP_PASSWORD` | If set, the app asks for this password before loading. |
| `DATA_PROVIDER` | `yahoo` (default, free/delayed) or `eodhd` (real-time/paid). |
| `EODHD_API_KEY` | API key when `DATA_PROVIDER=eodhd`. |
| `ANTHROPIC_API_KEY` | If set (and `pip install anthropic`), the Stock tab shows an AI news summary. |
| `NTFY_TOPIC` | Push alerts via ntfy.sh (free, no account) — used by the alert runner. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `ALERT_EMAIL_TO` | Email alerts. |

## Architecture

```
app.py           Streamlit UI only (no direct data-source calls)
providers.py     Data behind one interface — YahooProvider + EODHDProvider (swap via env)
store.py         SQLite ledger, notes, alerts (positions are derived, not stored)
portfolio.py     Pure holdings/return maths (time-weighted return)
analytics.py     Pure backtest, XIRR, risk metrics, Monte Carlo, efficient frontier
taxlots.py       Pure FIFO lot accounting + tax report
importers.py     Pure broker-CSV → transactions normaliser
alerts.py        Pure alert-condition logic (shared by app + runner)
notify.py        Email (SMTP) + push (ntfy) delivery
alert_runner.py  Standalone cron job: check alerts and notify while the app is closed
```

The provider seam means moving to a paid/real-time feed is a config change, not a rewrite.

## Extra features

- **Multiple portfolios** — switch or create one in the sidebar; every tab scopes to it.
- **Broker-CSV import** — upload a Nordnet/DNB/Saxo export in the Portfolio tab and map
  the columns; Nordic action words (Kjøpt/Solgt/Utbytte…) are recognised automatically.
- **Efficient frontier** — in the Risk tab, sample thousands of weightings and highlight
  the max-Sharpe and min-volatility mixes.
- **Editable watchlist** — add/remove tickers in the sidebar; saved to the DB, no code edit needed (the built-in Oslo Børs names are just the starting seed).
- **CSV export** — download transactions, positions and the FIFO tax report from the Portfolio tab.
- **Alerts** — set price/RSI triggers in the Market tab; checked each time you open or
  refresh (a local app has no background monitoring).

## Tests

```bash
pip install pytest
pytest -q
```

Covers the money logic: average-cost basis, realised P/L, cash, time-weighted
return, XIRR, DCA, beta and Monte Carlo — all on synthetic data, no network.

## Deploy

- **Locally**: just `streamlit run app.py` (recommended for private financial data).
- **Docker**:
  ```bash
  docker build -t oslo-desk .
  docker run -p 8501:8501 -v $PWD/data:/data -e APP_PASSWORD=changeme oslo-desk
  ```
  The `-v` mount keeps `portfolio.db` outside the container so it survives restarts.
- **Streamlit Community Cloud**: works, but the filesystem is ephemeral — set
  `PORTFOLIO_DB` to a mounted/managed store, or treat it as read-only/demo.

## Background alerts (24/7)

The app checks alerts on load, but for monitoring while it's closed, run the standalone
checker on a schedule. It notifies only on the transition into "triggered", so a
standing condition won't spam you.

```bash
export NTFY_TOPIC=oslo-desk-pick-something-random   # push (free), or set SMTP_* for email
export PORTFOLIO_DB=/data/portfolio.db              # same DB the app uses
python alert_runner.py                              # run once
```

cron (every 15 min):
```
*/15 * * * *  cd /path/to/app && /usr/bin/python3 alert_runner.py >> alerts.log 2>&1
```

## Switching to real-time data

```bash
export DATA_PROVIDER=eodhd
export EODHD_API_KEY=your_key
streamlit run app.py
```

`EODHDProvider` implements the same interface as the default Yahoo one; verify EODHD's
endpoint/field names against their current docs (linked in `providers.py`).

## Development

```bash
make install     # deps
make run         # launch the app
make test        # run the test suite (16 tests)
make lint        # ruff, if installed
make alerts      # run the background alert checker once
```

`pyproject.toml` holds pytest/ruff config; copy `.env.example` to `.env` for local secrets.

## Honest limits

- Prices are **delayed ~15 min** (Yahoo Finance), fine for a decision helper, not intraday trading.
- FX on the performance chart uses a constant current rate, so it doesn't capture
  currency swings over time (irrelevant while you're all-NOK).
- Signals and Monte Carlo are backward-looking and simplistic — research aids, not forecasts.

## What's next (from ROADMAP.md)

Every roadmap phase and follow-up is implemented: multiple portfolios, CSV import,
efficient frontier, alerts (with a background runner), a second real-time provider
(EODHD), and FIFO tax-lot accounting. Remaining ideas are genuinely optional polish —
intraday charts, more broker CSV presets, and a hosted multi-user version.
