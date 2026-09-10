# Oslo Børs Trading Desk — Improvement Roadmap

A structured path from the current prototype to a solid personal decision tool.
Ordered so each phase builds on the last. Effort is rough dev-time; do the
**critical-path** items in order, then pick from the rest by what you'll actually use.

---

## Guiding principle: two foundations first

Almost everything you asked for (real-time data, dividends, FX, news, smarter
assistance) depends on two architectural decisions. Get these right early and the
rest slots in; skip them and you'll rewrite `app.py` repeatedly.

1. **Where data comes from** → `providers.py` (a swappable data interface).
2. **How the portfolio is stored** → `store.py` (a transaction ledger, positions derived).

Both starter files are already in this folder, tested and ready to wire in. That's
Phase 0.

**Critical path:** Phase 0 → Phase 1 (data) → Phase 2 (portfolio depth) → then
cherry-pick Phases 3–5.

---

## Phase 0 — Wire in the foundations *(½–1 day)*

| Task | Why | Effort |
|---|---|---|
| Replace direct `yfinance` calls in `app.py` with `providers.get_provider()` | One place to swap data sources later | S |
| Replace `portfolio.json` with `store.py` (SQLite ledger) | Enables sells, dividends, realised P/L | M |
| Migrate the Portfolio tab to add **transactions** (BUY/SELL/DIV) instead of static holdings | Correct model for everything downstream | M |

**Done when:** you can record a buy, a sell, and a dividend, and the portfolio math
still adds up (`store.py`'s self-test shows the shape).

---

## Phase 1 — Data layer *(1–3 days)*

| Task | Why | Effort | Priority |
|---|---|---|---|
| Decide **delayed vs real-time** (Yahoo free vs EODHD/Infront paid) | Shapes cost & architecture; do it consciously | S | ★★★ |
| Add `get_fundamentals` usage (P/E, yield, market cap) to Stock explorer | Basic quality/valuation context | S | ★★★ |
| **FX handling** — convert non-NOK holdings to a NOK base | Correct totals once you hold US/EU stocks | M | ★★☆ |
| Centralise caching + a "data health" indicator (last update, stale warning) | Trust the numbers you see | S | ★★☆ |
| Optional: second provider class to prove the interface swaps cleanly | De-risks a future paid feed | M | ★☆☆ |

**Real-time note:** truly live Oslo Børs quotes require a licensed feed (Euronext/
Infront) or a paid API tier. For a *decision helper*, delayed data is usually fine —
spend the money only if you'll act intraday.

---

## Phase 2 — Portfolio depth *(2–4 days)*

| Task | Why | Effort | Priority |
|---|---|---|---|
| Realised vs unrealised P/L, incl. dividends & fees | The honest picture of returns | M | ★★★ |
| Cash balance + deposits/withdrawals | Track money-weighted returns | M | ★★☆ |
| Portfolio-vs-OBX performance chart (time-weighted) | "Am I beating the index?" | M | ★★★ |
| Multiple named portfolios (e.g. "Long-term", "Speculative") | Separate strategies | S | ★☆☆ |
| Import from broker CSV (Nordnet / DNB / Saxo export) | Stop manual entry | M | ★★☆ |

---

## Phase 3 — Analytics & simulation *(3–5 days)*

| Task | Why | Effort | Priority |
|---|---|---|---|
| Backtest upgrades: periodic rebalancing + monthly DCA | Realistic strategy testing | M | ★★☆ |
| Correlation matrix + portfolio beta vs OBX | See real diversification | M | ★★☆ |
| Monte Carlo projection (fan chart of future value) | Range of outcomes, not one guess | M | ★★☆ |
| Allocation optimiser (efficient frontier) | Suggest weights for a risk target | L | ★☆☆ |
| Risk metrics: VaR, downside deviation, Sortino | Understand tail risk | M | ★☆☆ |

---

## Phase 4 — Decision assistance *(3–6 days)*

| Task | Why | Effort | Priority |
|---|---|---|---|
| Configurable signal rules (weights/thresholds in UI) | Make the score *yours*, not a black box | M | ★★☆ |
| Fundamentals screen (yield, P/E, payout, debt) with filters | Find candidates, not just chart signals | M | ★★★ |
| Per-stock news via `provider` + optional **LLM summary** | Fast context on why a stock moved | M | ★★☆ |
| Price/indicator **alerts** (email or in-app) | Don't babysit the screen | M | ★☆☆ |
| A written "thesis + checklist" note per holding | Forces discipline; beats gut calls | S | ★★☆ |

> Keep every signal **transparent and rule-based**, and keep the "not financial
> advice" framing. The tool should surface information and enforce your own rules —
> not tell you what to buy.

---

## Phase 5 — Productionising *(only if you host it) (2–4 days)*

| Task | Why | Effort |
|---|---|---|
| Move storage off ephemeral disk (SQLite→managed Postgres/Supabase) | Cloud filesystems reset | M |
| Auth (single-user password / OAuth) | It's your money data | M |
| Scheduled data refresh / caching job | Faster loads, fewer API hits | M |
| Basic tests around `store.compute_positions` and P/L math | Don't let a refactor corrupt returns | M |
| Deploy (Streamlit Community Cloud / a small VPS / Docker) | Access it anywhere | M |

---

## How to use this doc

- Treat each **★★★** row as "do next"; **★☆☆** as "nice to have someday".
- Keep it in the repo and tick items off as you go.
- Don't jump to Phase 3/4 features on the JSON foundation — Phase 0 first, always.

## Recommended first three sessions

1. **Wire in `store.py`** — convert Portfolio to transactions (Phase 0).
2. **Wire in `providers.py`** + add fundamentals to Stock explorer (Phase 0–1).
3. **Portfolio-vs-OBX** time-weighted performance + realised P/L (Phase 2).
