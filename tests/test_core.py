"""
Core maths tests — the money logic must never silently break in a refactor.

Run:  pip install pytest && pytest -q
These tests use synthetic data only; no network or Streamlit required.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import analytics as an
import alerts as alert_logic
import importers as imp
import portfolio as pf
import store
import taxlots


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    return store


# --------------------------------------------------------------------------- #
# store.py — positions, realised P/L, cash
# --------------------------------------------------------------------------- #
def test_average_cost_and_realised_pl(temp_db):
    s = temp_db
    s.add_transaction("2024-01-02", "EQNR.OL", "BUY", 100, 300, fee=29)
    s.add_transaction("2024-06-01", "EQNR.OL", "BUY", 50, 280, fee=29)
    s.add_transaction("2024-09-01", "EQNR.OL", "SELL", 60, 330, fee=29)
    pos = s.compute_positions().set_index("ticker")
    avg = (100 * 300 + 29 + 50 * 280 + 29) / 150
    assert pos.loc["EQNR.OL", "avg_cost"] == pytest.approx(avg)
    assert pos.loc["EQNR.OL", "realised"] == pytest.approx(60 * (330 - avg) - 29)
    assert pos.loc["EQNR.OL", "shares"] == pytest.approx(90)


def test_cash_and_deposits_ignore_positions(temp_db):
    s = temp_db
    s.add_transaction("2024-01-01", "CASH", "DEPOSIT", price=50000)
    s.add_transaction("2024-01-02", "EQNR.OL", "BUY", 100, 300, fee=29)
    s.add_transaction("2024-06-01", "EQNR.OL", "SELL", 40, 330, fee=29)
    s.add_transaction("2024-05-01", "EQNR.OL", "DIV", price=800)
    s.add_transaction("2024-07-01", "CASH", "WITHDRAW", price=5000)
    tx = s.get_transactions()
    expected = 50000 - (100 * 300 + 29) + (40 * 330 - 29) + 800 - 5000
    assert s.compute_cash(tx) == pytest.approx(expected)
    assert s.net_deposits(tx) == pytest.approx(45000)
    assert "CASH" not in set(s.compute_positions(tx)["ticker"])


def test_notes_upsert(temp_db):
    s = temp_db
    assert s.get_note("EQNR.OL") == ""
    s.set_note("EQNR.OL", "first")
    s.set_note("eqnr.ol", "second")  # case-insensitive upsert
    assert s.get_note("EQNR.OL") == "second"


def test_watchlist_seed_add_remove(temp_db):
    s = temp_db
    s.seed_watchlist({"EQNR.OL": "Equinor", "DNB.OL": "DNB Bank"})
    s.seed_watchlist({"XXX.OL": "should-not-reseed"})  # only seeds when empty
    wl = s.get_watchlist()
    assert wl == {"EQNR.OL": "Equinor", "DNB.OL": "DNB Bank"}
    s.add_watchlist("NEL.OL", "Nel")
    assert s.get_watchlist()["NEL.OL"] == "Nel"
    s.remove_watchlist("dnb.ol")  # case-insensitive
    assert "DNB.OL" not in s.get_watchlist()


# --------------------------------------------------------------------------- #
# portfolio.py — time-weighted return neutralises flows
# --------------------------------------------------------------------------- #
def test_twr_neutralises_contributions():
    dates = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"])
    prices = pd.DataFrame({"AAA": [100, 110, 110, 121]}, index=dates)
    tx = pd.DataFrame([
        {"date": "2024-01-01", "ticker": "AAA", "type": "BUY", "quantity": 10, "price": 100, "fee": 0},
        {"date": "2024-01-03", "ticker": "AAA", "type": "BUY", "quantity": 10, "price": 110, "fee": 0},
    ])
    sh = pf.shares_over_time(tx, prices.index)
    val = pf.holdings_value(sh, prices)
    fl = pf.external_flows(tx, prices.index)
    twr = pf.twr_index(val, fl)
    assert twr.iloc[0] == pytest.approx(1.00)
    assert twr.iloc[1] == pytest.approx(1.10)
    assert twr.iloc[2] == pytest.approx(1.10)  # doubling the position doesn't move TWR
    assert twr.iloc[3] == pytest.approx(1.21)


# --------------------------------------------------------------------------- #
# analytics.py — XIRR, DCA, risk, MC
# --------------------------------------------------------------------------- #
def test_xirr_known_rate():
    cf = [(pd.Timestamp("2023-01-01"), -1000), (pd.Timestamp("2024-01-01"), 1100)]
    assert an.xirr(cf) == pytest.approx(0.10, abs=1e-3)


def test_dca_flat_price_conserves_capital():
    dates = pd.date_range("2023-01-02", "2023-12-29", freq="B")
    flat = pd.DataFrame({"AAA": [100.0] * len(dates)}, index=dates)
    val, inv, _ = an.dca_backtest(flat, {"AAA": 1}, initial=0, monthly=1000)
    assert inv.iloc[-1] == pytest.approx(12000)
    assert val.iloc[-1] == pytest.approx(inv.iloc[-1])


def test_beta_recovers_slope():
    rng = np.random.default_rng(3)
    mkt = pd.Series(rng.normal(0.0004, 0.01, 500))
    asset = 1.3 * mkt + pd.Series(rng.normal(0, 0.004, 500))
    assert an.beta(asset, mkt) == pytest.approx(1.3, abs=0.2)


def test_monte_carlo_shapes_and_ordering():
    rng = np.random.default_rng(1)
    ret = pd.Series(rng.normal(0.0005, 0.012, 400))
    bands, ends = an.monte_carlo(ret, start_value=100000, days=252, n=1000)
    assert len(bands[50]) == 253 and len(ends) == 1000
    assert np.percentile(ends, 5) < np.median(ends) < np.percentile(ends, 95)


# --------------------------------------------------------------------------- #
# Multiple portfolios, alerts, CSV import, efficient frontier
# --------------------------------------------------------------------------- #
def test_multiple_portfolios_isolated(temp_db):
    s = temp_db
    s.add_transaction("2024-01-02", "EQNR.OL", "BUY", 100, 300, portfolio="Long-term")
    s.add_transaction("2024-01-03", "NAS.OL", "BUY", 500, 10, portfolio="Speculative")
    assert set(s.list_portfolios()) == {"Long-term", "Speculative"}
    assert len(s.get_transactions("Long-term")) == 1
    assert len(s.get_transactions()) == 2


def test_alerts_crud(temp_db):
    s = temp_db
    s.add_alert("EQNR.OL", "price_above", 350)
    s.add_alert("NAS.OL", "price_below", 8)
    al = s.list_alerts()
    assert len(al) == 2
    s.delete_alert(int(al.iloc[0]["id"]))
    assert len(s.list_alerts()) == 1


def test_importer_maps_nordic_terms_and_abs():
    raw = pd.DataFrame({
        "Handledato": ["2024-02-01", "2024-02-03", "2024-02-10"],
        "Verdipapir": ["eqnr.ol", "dnb.ol", "cash"],
        "Transaksjonstype": ["Kjøpt", "Solgt", "Innskudd"],
        "Antall": [10, -5, 0], "Kurs": [305.5, 210.0, 0], "Avgift": [29, 29, 0]})
    norm = imp.normalize_transactions(raw, {
        "date": "Handledato", "ticker": "Verdipapir", "type": "Transaksjonstype",
        "quantity": "Antall", "price": "Kurs", "fee": "Avgift"})
    assert list(norm["type"]) == ["BUY", "SELL", "DEPOSIT"]
    assert norm["quantity"].iloc[1] == 5.0  # negative made positive


def test_efficient_frontier_weights_sum_to_one():
    rng = np.random.default_rng(0)
    px = pd.DataFrame({t: 100 * np.cumprod(1 + rng.normal(0.0004, 0.012, 400))
                       for t in ["A", "B", "C"]})
    cloud, hi = an.efficient_frontier(px, n=2000)
    assert cloud.shape == (2000, 3)
    assert abs(sum(hi["max_sharpe"]["weights"].values()) - 1.0) < 1e-6
    assert hi["min_vol"]["vol"] <= cloud["vol"].median()


# --------------------------------------------------------------------------- #
# FIFO tax lots + alert logic
# --------------------------------------------------------------------------- #
def test_fifo_matches_oldest_lots():
    tx = pd.DataFrame([
        {"id": 1, "date": "2023-01-02", "ticker": "EQNR.OL", "type": "BUY", "quantity": 100, "price": 300, "fee": 0},
        {"id": 2, "date": "2023-06-01", "ticker": "EQNR.OL", "type": "BUY", "quantity": 50, "price": 280, "fee": 0},
        {"id": 3, "date": "2023-09-01", "ticker": "EQNR.OL", "type": "SELL", "quantity": 60, "price": 330, "fee": 0},
    ])
    pos = taxlots.fifo_positions(tx).set_index("ticker")
    assert pos.loc["EQNR.OL", "realised"] == pytest.approx(1800)   # 60*(330-300)
    assert pos.loc["EQNR.OL", "shares"] == pytest.approx(90)
    assert pos.loc["EQNR.OL", "avg_cost"] == pytest.approx((40 * 300 + 50 * 280) / 90)
    rep = taxlots.fifo_realised(tx)
    assert rep["gain"].sum() == pytest.approx(1800)
    assert list(taxlots.open_lots(tx)["shares"]) == [40.0, 50.0]


def test_fifo_differs_from_average_cost(temp_db):
    s = temp_db
    for d, ty, q, p in [("2023-01-02", "BUY", 100, 300), ("2023-06-01", "BUY", 50, 280),
                        ("2023-09-01", "SELL", 60, 330)]:
        s.add_transaction(d, "EQNR.OL", ty, q, p, fee=0)
    tx = s.get_transactions()
    avg = s.compute_positions(tx).set_index("ticker").loc["EQNR.OL", "realised"]
    fifo = taxlots.fifo_positions(tx).set_index("ticker").loc["EQNR.OL", "realised"]
    assert avg == pytest.approx(2200) and fifo == pytest.approx(1800)


def test_alert_conditions():
    ec = alert_logic.evaluate_condition
    assert ec("price_above", 350, price=360)
    assert not ec("price_above", 350, price=340)
    assert ec("price_below", 8, price=7.5)
    assert ec("rsi_below", 30, rsi=28)
    assert not ec("rsi_above", 70, rsi=65)
    assert not ec("price_above", 1, price=None)
    adf = pd.DataFrame([{"id": 1, "ticker": "EQNR.OL", "kind": "price_above", "value": 300},
                        {"id": 2, "ticker": "NAS.OL", "kind": "rsi_below", "value": 30}])
    res = alert_logic.evaluate_all(adf, price_fn=lambda t: 320, rsi_fn=lambda t: 25)
    assert res[0]["triggered"] and res[1]["triggered"]
