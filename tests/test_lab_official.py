import json
import sys
import types

import numpy as np
import pandas as pd
import pytest

from bot import config, fx, lab

IDX = pd.bdate_range("2026-01-01", periods=30)


def fake_yf(calls):
    def download(syms, **kw):
        calls.append(list(syms))
        cols = pd.MultiIndex.from_product([syms, ["Close", "High", "Low", "Open"]])
        return pd.DataFrame(np.full((len(IDX), len(cols)), 100.0), index=IDX, columns=cols)
    return types.SimpleNamespace(download=download)


def test_load_history_converts_to_euro_and_caches(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf(calls))
    monkeypatch.setattr(fx, "download_rates", lambda ccys, period=None, start=None, **k: pd.DataFrame({"USD": 1.25}, index=IDX))
    cache = str(tmp_path / "cache" / "history_official.pkl")
    h = lab.load_history(cache, symbols=["AAA", "BBB.DE"], currencies={"AAA": "USD", "BBB.DE": "EUR"})
    assert set(h) == {"close", "high", "low", "open"}
    assert h["close"]["AAA"].iloc[0] == pytest.approx(80.0) and h["close"]["BBB.DE"].iloc[0] == 100.0        # Dollar-Kurs in Euro, Euro-Kurs unverändert
    assert h["close"]["^GSPC"].iloc[0] == 100.0                                                                # Indizes bleiben unverändert
    assert h["open"]["AAA"].iloc[0] == pytest.approx(80.0) and len(calls) == 1
    lab.load_history(cache, symbols=["AAA", "BBB.DE"], currencies={"AAA": "USD", "BBB.DE": "EUR"})
    assert len(calls) == 1                                                                                      # zweiter Aufruf aus dem Zwischenspeicher


def test_load_history_without_currencies_keeps_local_prices(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf([]))
    h = lab.load_history(str(tmp_path / "h.pkl"), symbols=["AAA"])
    assert h["close"]["AAA"].iloc[0] == 100.0


def test_official_report_needs_a_universe_from_the_official_import(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    (tmp_path / "universe.json").write_text(json.dumps([{"isin": "SAP.DE", "name": "SAP", "yf": "SAP.DE"}]))
    with pytest.raises(SystemExit, match="official"):
        lab._official_report(False, False)


# --- Nachhaltigkeitsertrag ---
def test_nh_yield_sums_gains_of_traded_star_titles_only():
    sim = {"flows": {"A": [8000.0, 0.0], "B": [8000.0, 9500.0], "C": [8000.0, 0.0]}, "held_value": {"A": 9000.0, "C": 7000.0}}
    assert lab.nh_yield(sim, {"A", "B"}) == pytest.approx((9000 - 8000) + (9500 - 8000))            # A hält 1.000 Gewinn (unrealisiert), B 1.500 realisiert; C ohne Stern zählt nicht
    assert lab.nh_yield(sim, {"C"}) == pytest.approx(-1000.0) and lab.nh_yield(sim, set()) == 0.0
    assert lab.nh_yield({"flows": {}, "held_value": {}}, {"A"}) == 0.0


def test_random_nh_yields_are_sums_of_equal_sized_positions():
    class Fr:
        a = {"price": np.array([[100.0, 100.0, 100.0, 100.0], [110.0, 90.0, 120.0, np.nan]])}
        col_index = {"A": 0, "B": 1, "C": 2, "D": 3, "X": 4}
    h = types.SimpleNamespace(fr=Fr)
    y = lab.random_nh_yields(h, 0, 1, {"A", "B", "C", "D"}, n=50, k=3, amount=1000.0)
    # D hat am Ende keinen Kurs und entfällt; die drei übrigen (+10 %, -10 %, +20 %) ergeben genau eine Kombination
    assert np.allclose(y, 1000.0 * (0.10 - 0.10 + 0.20))
    y2 = lab.random_nh_yields(h, 0, 1, {"A", "B", "C"}, n=50, k=2, amount=1000.0)
    assert set(np.round(y2, 6)) <= {0.0, 300.0, 100.0}                                                # Paare: A+B = 0, A+C = 300, B+C = 100
