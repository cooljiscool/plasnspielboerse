import os
import time

import numpy as np
import pandas as pd
import pytest

from bot import config, fx

IDX = pd.bdate_range("2026-09-01", periods=6)


@pytest.mark.parametrize("sym,ccy", [("AAPL", "USD"), ("BRK-B", "USD"), ("SAP.DE", "EUR"), ("TTE.PA", "EUR"), ("ADYEN.AS", "EUR"), ("ISP.MI", "EUR"), ("VOE.VI", "EUR"),
                                     ("HM-B.ST", "SEK"), ("COLO-B.CO", "DKK"), ("SREN.SW", "CHF"), ("CTEC.L", "GBp"), ("CNR.TO", "CAD"), ("XYZ.ZZ", None)])
def test_currency_is_inferred_from_the_exchange_suffix(sym, ccy):
    assert fx.infer_currency(sym) == ccy


def test_rate_symbols_use_the_main_currency():
    assert fx.rate_symbol("USD") == "EURUSD=X" and fx.rate_symbol("GBp") == "EURGBP=X" and fx.rate_symbol("SEK") == "EURSEK=X"


def test_convert_divides_by_the_daily_rate_and_handles_pence():
    close = pd.DataFrame({"AAPL": [100.0] * 6, "SHEL.L": [2500.0] * 6, "SAP.DE": [200.0] * 6, "^GSPC": [5000.0] * 6}, index=IDX)
    rates = pd.DataFrame({"USD": [1.25, 1.25, 1.10, 1.10, 1.10, 1.10], "GBP": [0.80] * 6}, index=IDX)
    out = fx.convert(close, {"AAPL": "USD", "SHEL.L": "GBp", "SAP.DE": "EUR"}, rates)
    assert out["AAPL"].tolist() == pytest.approx([80.0, 80.0, 100 / 1.10, 100 / 1.10, 100 / 1.10, 100 / 1.10])   # Dollar fällt: Euro-Kurs steigt
    assert out["SHEL.L"].iloc[0] == pytest.approx(2500 / 100 / 0.80)                                                   # 2.500 Pence = 25 £ = 31,25 €
    assert out["SAP.DE"].tolist() == [200.0] * 6 and out["^GSPC"].tolist() == [5000.0] * 6                            # Euro-Titel und Indizes unverändert
    assert close["AAPL"].iloc[0] == 100.0                                                                              # Eingabe bleibt unverändert


def test_convert_fills_holiday_gaps_but_never_invents_a_price_without_a_rate():
    close = pd.DataFrame({"AAPL": [100.0] * 6, "SEKAKTIE.ST": [500.0] * 6}, index=IDX)
    rates = pd.DataFrame({"USD": [1.2, np.nan, np.nan, 1.2, 1.2, 1.2]}, index=IDX)                                   # Lücke von zwei Tagen
    out = fx.convert(close, {"AAPL": "USD", "SEKAKTIE.ST": "SEK"}, rates)
    assert out["AAPL"].notna().all() and out["AAPL"].iloc[1] == pytest.approx(100 / 1.2)
    assert out["SEKAKTIE.ST"].isna().all()                                                                             # keine Krone-Kurse: leer statt unumgerechnet


def test_convert_leaves_early_days_without_rate_empty():
    close = pd.DataFrame({"AAPL": [100.0] * 6}, index=IDX)
    rates = pd.DataFrame({"USD": [1.2] * 3}, index=IDX[3:])
    out = fx.convert(close, {"AAPL": "USD"}, rates)
    assert out["AAPL"].iloc[:3].isna().all() and out["AAPL"].iloc[3] == pytest.approx(100 / 1.2)


def fake_fetch(calls):
    def fetch(syms):
        calls.append(list(syms))
        return pd.DataFrame({s: [1.1, 1.2, 1.3] for s in syms}, index=IDX[:3])
    return fetch


def test_download_rates_names_columns_by_currency_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    calls = []
    r = fx.download_rates(["USD", "GBp", "EUR", "USD", None], fetch=fake_fetch(calls))
    assert sorted(r.columns) == ["GBP", "USD"] and calls == [["EURGBP=X", "EURUSD=X"]]
    assert os.path.exists(tmp_path / "cache" / "fx_rates.pkl")
    assert fx.download_rates(["EUR"]).empty                                       # nur Euro: nichts zu holen


def test_download_rates_falls_back_to_fresh_cache_but_not_to_stale_or_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    fx.download_rates(["USD"], fetch=fake_fetch([]))

    def down(syms):
        raise RuntimeError("Yahoo down")
    assert fx.download_rates(["USD"], fetch=down)["USD"].iloc[-1] == 1.3          # frischer Zwischenspeicher
    with pytest.raises(RuntimeError):
        fx.download_rates(["USD", "SEK"], fetch=down)                              # SEK fehlt im Zwischenspeicher
    old = time.time() - 8 * 86400
    os.utime(tmp_path / "cache" / "fx_rates.pkl", (old, old))
    with pytest.raises(RuntimeError):
        fx.download_rates(["USD"], fetch=down)                                     # zu alt


def test_download_rates_rejects_a_currency_without_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "leer"))

    def partial(syms):
        return pd.DataFrame({syms[0]: [1.1, 1.2], syms[1]: [np.nan, np.nan]}, index=IDX[:2])
    with pytest.raises(RuntimeError, match="keine Wechselkurse"):
        fx.download_rates(["USD", "SEK"], fetch=partial)
