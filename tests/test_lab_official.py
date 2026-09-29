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
