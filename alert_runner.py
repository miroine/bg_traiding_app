#!/usr/bin/env python3
"""
Background alert runner.

A local Streamlit app can't watch prices while it's closed, so run this on a
schedule and it will check every alert and deliver a notification when one fires.
It only notifies on the *transition* into "triggered" (tracked by the `notified`
flag), so a standing condition won't spam you every run; when the condition clears,
the flag resets so it can fire again later.

Set up notifications (see notify.py) and, optionally, the data source:
    export NTFY_TOPIC=oslo-desk-something-random      # push, or configure SMTP_* for email
    export PORTFOLIO_DB=/data/portfolio.db            # same DB the app uses

Run once:
    python alert_runner.py

Every 15 min via cron:
    */15 * * * *  cd /path/to/app && /usr/bin/python3 alert_runner.py >> alerts.log 2>&1
"""

import sys

import alerts as alert_logic
import analytics as an
import notify
import store
from providers import get_provider


def main() -> int:
    df = store.list_alerts()
    if df.empty:
        print("No alerts configured.")
        return 0

    prov = get_provider()

    def price_fn(ticker):
        return prov.get_quote(ticker).get("price")

    def rsi_fn(ticker):
        s = prov.get_history(ticker, "6mo")["Close"]
        return float(an.rsi(s).iloc[-1])

    results = alert_logic.evaluate_all(df, price_fn, rsi_fn)
    prev = dict(zip(df["id"], df.get("notified", [0] * len(df))))

    fired, cleared = 0, 0
    for r in results:
        was = bool(prev.get(r["id"], 0))
        now = r["triggered"]
        if now and not was:
            msg = alert_logic.describe(r, r["current"])
            channels = notify.notify("🔔 Oslo Børs alert", msg)
            store.set_alert_notified(r["id"], True)
            fired += 1
            print(f"FIRED  {msg}  → sent via {channels or 'no channel configured'}")
        elif not now and was:
            store.set_alert_notified(r["id"], False)
            cleared += 1

    print(f"Checked {len(results)} alerts · {fired} fired · {cleared} reset.")
    if fired and not notify.channels_configured():
        print("WARNING: alerts fired but no delivery channel is configured "
              "(set NTFY_TOPIC or SMTP_*).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
